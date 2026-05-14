"""Verification service -- uses an AI Judge to verify autofill extractions.

Hardening summary (anti-hallucination):
- Payload includes the actual question text, field type, allowed options and
  where_to_verify so the judge can ground its decisions.
- Gemini's confidence/justification are intentionally NOT forwarded to avoid
  anchoring bias.
- OpenAI calls use a strict JSON Schema response_format with a mandatory
  ``evidence_quote`` field. If the model rejects the schema, fallback is one
  retry with ``json_object`` and a warning log.
- Parser validates that ``evidence_quote`` is a verbatim substring of the
  evidence snippet; otherwise the verdict is degraded to ``needs_review`` so
  hallucinations cannot pose as approvals/rejections.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Mapping

from google.genai import types
from pydantic import BaseModel, ValidationError

from .extraction_service import _get_client
from .gemini_runtime_service import apply_thinking_config
from .rag_config import get_rag_settings
from ..prompts.verification_agent_prompts import (
    VERIFICATION_SYSTEM_PROMPT,
    build_verification_user_prompt,
)

log = logging.getLogger("verification_agent")

EVIDENCE_SNIPPET_MAX_CHARS = 4000
EVIDENCE_DISPLAY_MAX_CHARS = 1500

VALID_STATUSES = ("approved", "needs_review", "rejected")

VERIFICATION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["results"],
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "status", "evidence_quote", "reason"],
                "properties": {
                    "id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": list(VALID_STATUSES),
                    },
                    "evidence_quote": {
                        "type": "string",
                        "description": (
                            "Verbatim substring of evidence_snippet that justifies the decision. "
                            "Empty string only when status=needs_review."
                        ),
                    },
                    "reason": {
                        "type": "string",
                        "maxLength": 240,
                    },
                },
            },
        }
    },
}


class FieldVerificationResult(BaseModel):
    status: str  # "approved" | "needs_review" | "rejected"
    reason: str
    evidence_quote: str = ""


class BatchVerificationResponse(BaseModel):
    results: list[Any]


def _get_anthropic_client():
    """Lazily create and return an Anthropic client."""
    import anthropic

    settings = get_rag_settings()
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _get_openai_client():
    """Lazily create and return an OpenAI client."""
    from openai import OpenAI

    settings = get_rag_settings()
    return OpenAI(api_key=settings.openai_api_key)


def _call_gemini_batch(fields_payload: list[dict]) -> dict[str, FieldVerificationResult]:
    """Call Gemini with a batch of fields and parse the response."""
    settings = get_rag_settings()
    client = _get_client()
    user_prompt = build_verification_user_prompt(fields_payload)

    start = time.time()
    config_kwargs: dict[str, Any] = {
        "temperature": settings.verification_temperature,
        "max_output_tokens": settings.verification_max_tokens,
        "response_mime_type": "application/json",
        "response_json_schema": VERIFICATION_JSON_SCHEMA,
    }
    apply_thinking_config(config_kwargs, settings.gemini_verification_thinking_level)
    response = client.models.generate_content(
        model=settings.verification_model or settings.gemini_model,
        contents=[f"{VERIFICATION_SYSTEM_PROMPT}\n\n{user_prompt}"],
        config=types.GenerateContentConfig(**config_kwargs),
    )
    elapsed_ms = int((time.time() - start) * 1000)

    usage = getattr(response, "usage_metadata", None)
    input_tokens = getattr(usage, "prompt_token_count", 0) if usage else 0
    output_tokens = getattr(usage, "candidates_token_count", 0) if usage else 0
    log.info(
        "Verification batch (gemini/%s): %d fields, %d input tokens, %d output tokens, %dms",
        settings.verification_model or settings.gemini_model,
        len(fields_payload),
        input_tokens,
        output_tokens,
        elapsed_ms,
    )

    raw_text = (getattr(response, "text", "") or "").strip()
    return _parse_verification_response(raw_text, _snippets_by_id(fields_payload))


def _option_labels(raw_options: Any) -> list[dict[str, str]] | None:
    """Serialize questionnaire_options into a compact list for the judge.

    Returns ``None`` (omitted from payload) when there are no options to
    constrain the value, so the judge does not get distracted.
    """
    if not raw_options:
        return None
    items: list[dict[str, str]] = []
    for opt in raw_options:
        if isinstance(opt, Mapping):
            value = str(opt.get("value") or opt.get("id") or "").strip()
            label = str(opt.get("label") or opt.get("text") or value).strip()
            if value or label:
                items.append({"value": value, "label": label})
        else:
            txt = str(opt).strip()
            if txt:
                items.append({"value": txt, "label": txt})
    return items or None


def _build_field_payload(
    field_id: str,
    target: dict[str, Any],
    result: Mapping[str, Any],
    evidence_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a single field payload for the verification prompt.

    Intentionally OMITS gemini_confidence and gemini_justification: surfacing
    them anchors the judge towards the primary extractor's verdict.
    """
    evidence_text = str(evidence_bundle.get("text_context") or "")
    snippet = evidence_text[:EVIDENCE_SNIPPET_MAX_CHARS]

    payload: dict[str, Any] = {
        "field_id": field_id,
        "field_label": str(
            target.get("field_label") or target.get("field_name") or field_id
        ),
        "question_text": str(target.get("questionnaire_form_text") or ""),
        "field_type": str(
            target.get("field_type_hint") or target.get("field_type") or "text"
        ),
        "where_to_verify": str(target.get("questionnaire_where_to_verify") or ""),
        "section": str(target.get("questionnaire_section") or ""),
        "extracted_value": str(result.get("value") or ""),
        "evidence_snippet": snippet,
        "evidence_truncated": len(evidence_text) > EVIDENCE_SNIPPET_MAX_CHARS,
    }

    options = _option_labels(target.get("questionnaire_options"))
    if options:
        payload["allowed_options"] = options

    return payload


def _strip_json_fence(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_text = "\n".join(lines)
    return raw_text.strip()


def _normalize_verification_payload(parsed: Any) -> dict[str, Any]:
    if isinstance(parsed, list):
        log.info(
            "Verification response was a bare array (no 'results' envelope); wrapping it."
        )
        parsed = {"results": parsed}
    if not isinstance(parsed, dict):
        raise ValueError("verification response must be a JSON object or array")
    BatchVerificationResponse.model_validate(parsed)
    return parsed


def _extract_verification_payload(raw_text: str) -> dict[str, Any] | None:
    cleaned = _strip_json_fence(raw_text)
    if not cleaned:
        log.info("Verification provider returned empty content; marking batch for review.")
        return None

    decoder = json.JSONDecoder()
    starts = [idx for idx, char in enumerate(cleaned) if char in "{["]
    if 0 not in starts:
        starts.insert(0, 0)

    last_error: Exception | None = None
    for start in starts:
        try:
            candidate, _ = decoder.raw_decode(cleaned[start:])
            return _normalize_verification_payload(candidate)
        except (json.JSONDecodeError, ValidationError, ValueError) as exc:
            last_error = exc
            continue

    log.info(
        "Verification provider returned no usable JSON payload; marking batch for review: %s",
        str(last_error or "unknown parse error")[:240],
    )
    return None


_WS_RE = re.compile(r"\s+")


def _normalize_for_substring(text: str) -> str:
    """Lowercase and collapse whitespace for tolerant substring matching."""
    return _WS_RE.sub(" ", text.lower()).strip()


def _is_quote_in_snippet(quote: str, snippet: str) -> bool:
    """Return True if quote is a substring of snippet (case/whitespace-insensitive)."""
    if not quote.strip():
        return False
    return _normalize_for_substring(quote) in _normalize_for_substring(snippet)


def _parse_verification_response(
    raw_text: str,
    snippets_by_id: Mapping[str, str] | None = None,
) -> dict[str, FieldVerificationResult]:
    """Parse the provider JSON response into the verification map.

    Hardening:
    - Unknown statuses are degraded to ``needs_review`` with an explicit reason
      AND a warning log (no silent coercion).
    - For ``approved``/``rejected`` results the ``evidence_quote`` is required
      to be a verbatim substring of the evidence snippet. Any violation
      degrades the verdict to ``needs_review`` and is logged at INFO level.
    """
    parsed = _extract_verification_payload(raw_text)
    if parsed is None:
        return {}

    parsed_response = BatchVerificationResponse.model_validate(parsed)

    snippets_by_id = snippets_by_id or {}
    verification_map: dict[str, FieldVerificationResult] = {}

    field_ids = list(snippets_by_id.keys())
    for index, item in enumerate(parsed_response.results):
        if not isinstance(item, Mapping):
            fallback_field_id = field_ids[index] if index < len(field_ids) else ""
            log.info(
                "Malformed verification result received%s: %s",
                f" for field {fallback_field_id}" if fallback_field_id else "",
                str(item)[:200],
            )
            if fallback_field_id:
                verification_map[fallback_field_id] = FieldVerificationResult(
                    status="needs_review",
                    reason="judge returned malformed verification result",
                    evidence_quote="",
                )
            continue

        field_id = str(item.get("id") or "").strip()
        if not field_id:
            log.warning(
                "Verification result without id discarded: %s",
                str(item)[:200],
            )
            continue

        raw_status = str(item.get("status") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        quote = str(item.get("evidence_quote") or "").strip()

        if raw_status not in VALID_STATUSES:
            log.warning(
                "Verification field %s returned invalid status %r; degrading to needs_review",
                field_id,
                raw_status,
            )
            verification_map[field_id] = FieldVerificationResult(
                status="needs_review",
                reason="judge returned invalid status",
                evidence_quote="",
            )
            continue

        if raw_status in ("approved", "rejected"):
            if not quote:
                log.info(
                    "Verification field %s status=%s without evidence_quote; degrading to needs_review",
                    field_id,
                    raw_status,
                )
                verification_map[field_id] = FieldVerificationResult(
                    status="needs_review",
                    reason="judge could not cite supporting evidence",
                    evidence_quote="",
                )
                continue
            snippet = snippets_by_id.get(field_id, "")
            if snippet and not _is_quote_in_snippet(quote, snippet):
                log.info(
                    "Verification field %s cited text not present in evidence; degrading to needs_review",
                    field_id,
                )
                verification_map[field_id] = FieldVerificationResult(
                    status="needs_review",
                    reason="judge cited text not present in evidence",
                    evidence_quote="",
                )
                continue

        verification_map[field_id] = FieldVerificationResult(
            status=raw_status,
            reason=reason,
            evidence_quote=quote,
        )

    return verification_map


def _snippets_by_id(fields_payload: list[dict]) -> dict[str, str]:
    return {
        str(item.get("field_id") or ""): str(item.get("evidence_snippet") or "")
        for item in fields_payload
        if item.get("field_id")
    }


def _call_anthropic_batch(fields_payload: list[dict]) -> dict[str, FieldVerificationResult]:
    """Call Anthropic with a batch of fields and parse the response."""
    settings = get_rag_settings()
    client = _get_anthropic_client()

    user_prompt = build_verification_user_prompt(fields_payload)

    start = time.time()
    response = client.messages.create(
        model=settings.verification_model,
        max_tokens=settings.verification_max_tokens,
        temperature=settings.verification_temperature,
        system=VERIFICATION_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    elapsed_ms = int((time.time() - start) * 1000)

    input_tokens = getattr(response.usage, "input_tokens", 0)
    output_tokens = getattr(response.usage, "output_tokens", 0)
    log.info(
        "Verification batch (anthropic/%s): %d fields, %d input tokens, %d output tokens, %dms",
        settings.verification_model,
        len(fields_payload),
        input_tokens,
        output_tokens,
        elapsed_ms,
    )

    raw_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            raw_text += block.text

    return _parse_verification_response(raw_text, _snippets_by_id(fields_payload))


def _is_reasoning_model(model: str) -> bool:
    """Detect OpenAI reasoning-class models (o1/o3/o4/gpt-5 families)."""
    name = model.strip().lower()
    return (
        name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
        or name.startswith("gpt-5")
    )


def _openai_model_supports_temperature(model: str) -> bool:
    """Reasoning models do not accept a custom temperature."""
    return not _is_reasoning_model(model)


def _openai_max_completion_tokens(model: str, configured_max_tokens: int) -> int:
    """Reasoning tokens count against max_completion_tokens; raise the floor."""
    if _is_reasoning_model(model):
        return max(configured_max_tokens, 16384)
    return configured_max_tokens


def _extract_openai_message_text(response: Any) -> tuple[str, str]:
    """Extract text from OpenAI chat responses across SDK content shapes."""
    choices = getattr(response, "choices", []) or []
    if not choices:
        return "", "no choices returned"

    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", "")
    message = getattr(choice, "message", None)
    if message is None:
        return "", f"finish_reason={finish_reason}; no message returned"

    content = getattr(message, "content", "")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                chunks.append(str(part.get("text") or part.get("content") or ""))
            else:
                chunks.append(str(getattr(part, "text", "") or getattr(part, "content", "") or ""))
        text = "".join(chunks)
    else:
        text = str(content or "")

    refusal = str(getattr(message, "refusal", "") or "")
    detail = f"finish_reason={finish_reason}"
    if refusal:
        detail = f"{detail}; refusal={refusal[:200]}"
    return text.strip(), detail


def _build_openai_kwargs(
    fields_payload: list[dict],
    *,
    use_strict_schema: bool,
) -> dict[str, Any]:
    settings = get_rag_settings()
    user_prompt = build_verification_user_prompt(fields_payload)

    kwargs: dict[str, Any] = {
        "model": settings.verification_model,
        "max_completion_tokens": _openai_max_completion_tokens(
            settings.verification_model,
            settings.verification_max_tokens,
        ),
        "messages": [
            {"role": "system", "content": VERIFICATION_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }

    if use_strict_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "verification_batch",
                "strict": True,
                "schema": VERIFICATION_JSON_SCHEMA,
            },
        }
    else:
        kwargs["response_format"] = {"type": "json_object"}

    if _openai_model_supports_temperature(settings.verification_model):
        kwargs["temperature"] = settings.verification_temperature
    if _is_reasoning_model(settings.verification_model):
        kwargs["reasoning_effort"] = "low"

    return kwargs


def _call_openai_batch(fields_payload: list[dict]) -> dict[str, FieldVerificationResult]:
    """Call OpenAI with a batch of fields and parse the response.

    Uses strict JSON Schema; if the API rejects it (model unsupported), retries
    once with ``json_object`` and logs a warning so the regression is visible.
    """
    settings = get_rag_settings()
    client = _get_openai_client()

    kwargs = _build_openai_kwargs(fields_payload, use_strict_schema=True)
    start = time.time()
    try:
        response = client.chat.completions.create(**kwargs)
    except Exception as exc:
        log.warning(
            "OpenAI rejected json_schema for model=%s (%s); retrying with json_object once.",
            settings.verification_model,
            exc,
        )
        kwargs = _build_openai_kwargs(fields_payload, use_strict_schema=False)
        response = client.chat.completions.create(**kwargs)
    elapsed_ms = int((time.time() - start) * 1000)

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    log.info(
        "Verification batch (openai/%s): %d fields, %d input tokens, %d output tokens, %dms",
        settings.verification_model,
        len(fields_payload),
        input_tokens,
        output_tokens,
        elapsed_ms,
    )

    raw_text, response_detail = _extract_openai_message_text(response)
    if not raw_text:
        log.warning(
            "OpenAI verification returned empty content (%s, model=%s, output_tokens=%d).",
            response_detail,
            settings.verification_model,
            output_tokens,
        )
        return {}

    return _parse_verification_response(raw_text, _snippets_by_id(fields_payload))


def _call_verification_batch(fields_payload: list[dict]) -> dict[str, FieldVerificationResult]:
    settings = get_rag_settings()
    if settings.verification_provider == "gemini":
        return _call_gemini_batch(fields_payload)
    if settings.verification_provider == "anthropic":
        return _call_anthropic_batch(fields_payload)
    return _call_openai_batch(fields_payload)


def _missing_provider_api_key_message() -> str:
    settings = get_rag_settings()
    if settings.verification_provider == "gemini":
        if not settings.gemini_api_key:
            return "GEMINI_API_KEY not configured"
        return ""
    if settings.verification_provider == "anthropic":
        if not settings.anthropic_api_key:
            return "ANTHROPIC_API_KEY not configured"
        return ""
    if not settings.openai_api_key:
        return "OPENAI_API_KEY not configured"
    return ""


def _normalize_default_comparison_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"

    text = " ".join(str(value).split()).strip().lower()
    if text in {"true", "yes", "y", "1", "checked", "on"}:
        return "yes"
    if text in {"false", "no", "n", "0", "unchecked", "off"}:
        return "no"
    compact = re.sub(r"[^a-z0-9]+", " ", text).strip()
    if compact in {
        "ee uu",
        "e e u u",
        "estados unidos",
        "u s",
        "us",
        "usa",
        "united states",
        "united states of america",
    }:
        return "united states"
    return text


def _target_result_is_default_filled(
    target: Mapping[str, Any],
    result: Mapping[str, Any],
) -> bool:
    default_value = target.get("questionnaire_default_value")
    if default_value is None:
        return False
    if target.get("questionnaire_force_default"):
        return True

    return _normalize_default_comparison_value(
        result.get("value")
    ) == _normalize_default_comparison_value(default_value)


def _chunked(items: list, size: int):
    """Split a list into chunks of given size."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _display_evidence_for(
    field_id: str,
    judge_quote: str,
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    """Build the evidence string surfaced to the UI/persistence.

    Strategy:
    1. If the judge produced a verbatim quote, prefix it (so the user sees
       exactly what the auditor anchored on).
    2. Always append the original RAG snippet so reviewers can see the full
       context retrieved from the document. This guarantees the tooltip
       "Evidence from documents" section is populated whenever there was any
       RAG context, even if the judge degraded the verdict to needs_review.
    """
    bundle = evidence_by_id.get(field_id) or {}
    rag_text = str(bundle.get("text_context") or "").strip()
    rag_truncated = rag_text[:EVIDENCE_DISPLAY_MAX_CHARS]

    quote = (judge_quote or "").strip()
    if quote and rag_truncated:
        return f'Judge cited: "{quote}"\n\n--- Document context ---\n{rag_truncated}'
    if quote:
        return f'Judge cited: "{quote}"'
    return rag_truncated


def _call_verification_batch_with_missing_retries(
    fields_payload: list[dict],
) -> dict[str, FieldVerificationResult]:
    """Call the judge and retry missing fields individually.

    Providers occasionally return malformed or truncated JSON for large batches.
    Retrying only the missing fields preserves good batch results while keeping
    one bad response from dropping every verification in the batch.
    """
    batch_results = _call_verification_batch(fields_payload)
    expected_ids = [
        str(item.get("field_id") or "").strip()
        for item in fields_payload
        if str(item.get("field_id") or "").strip()
    ]
    missing_ids = [field_id for field_id in expected_ids if field_id not in batch_results]

    if missing_ids and len(fields_payload) > 1:
        log.info(
            "Verification batch returned %d/%d results; retrying %d missing fields individually.",
            len(batch_results),
            len(expected_ids),
            len(missing_ids),
        )
        payload_by_id = {
            str(item.get("field_id") or "").strip(): item
            for item in fields_payload
            if str(item.get("field_id") or "").strip()
        }
        for field_id in missing_ids:
            single_payload = payload_by_id.get(field_id)
            if not single_payload:
                continue
            single_result = _call_verification_batch([single_payload])
            if field_id in single_result:
                batch_results[field_id] = single_result[field_id]

    for field_id in expected_ids:
        if field_id not in batch_results:
            batch_results[field_id] = FieldVerificationResult(
                status="needs_review",
                reason="judge returned no usable verification response",
                evidence_quote="",
            )

    return batch_results


def verify_autofill_batch(
    *,
    results_by_id: Mapping[str, Mapping[str, Any]],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    targets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify extracted autofill values using the configured AI judge.

    Returns a dict mapping
    ``field_id -> {status, reason, evidence, evidence_quote, model}``.

    - ``evidence``: human-readable string for the badge tooltip and the
      ``QuestionnaireAnswer.verification_evidence`` column. Combines the
      judge's verbatim quote (when available) with the original RAG snippet
      so reviewers always see where the answer came from.
    - ``evidence_quote``: the raw verbatim quote chosen by the judge (may be
      empty when the verdict is ``needs_review``).

    Returns {} silently if verification is disabled or on any failure.
    """
    settings = get_rag_settings()

    if not settings.verification_enabled:
        return {}
    missing_key_message = _missing_provider_api_key_message()
    if missing_key_message:
        log.debug("Verification skipped: %s", missing_key_message)
        return {}

    fields_to_verify: list[tuple[str, dict[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    for target in targets:
        field_id = str(target.get("id") or "").strip()
        if not field_id:
            continue
        result = results_by_id.get(field_id) or {}
        value = str(result.get("value") or "").strip()
        if not value:
            continue
        if _target_result_is_default_filled(target, result):
            continue
        evidence_bundle = evidence_by_id.get(field_id) or {}
        fields_to_verify.append((field_id, target, result, evidence_bundle))

    if not fields_to_verify:
        return {}

    verification_map: dict[str, Any] = {}

    try:
        for batch in _chunked(fields_to_verify, settings.verification_batch_size):
            payload = [
                _build_field_payload(field_id, target, result, evidence)
                for field_id, target, result, evidence in batch
            ]
            batch_results = _call_verification_batch_with_missing_retries(payload)
            for field_id, result in batch_results.items():
                verification_map[field_id] = {
                    "status": result.status,
                    "reason": result.reason,
                    "evidence": _display_evidence_for(
                        field_id, result.evidence_quote, evidence_by_id
                    ),
                    "evidence_quote": result.evidence_quote,
                    "model": settings.verification_model,
                }
    except Exception as exc:
        log.warning("Verification agent failed (non-blocking): %s", exc)
        return verification_map

    log.info("Verification completed: %d fields verified", len(verification_map))
    return verification_map
