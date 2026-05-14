"""Gemini-powered extraction of PDF field values from RAG evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import logging
import re
from typing import Any

from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from ..prompts.form_filling_prompts import (
    FORM_FILL_CACHE_PLACEHOLDER,
    build_field_extraction_batch_json_payload,
    build_batch_request_prompt,
    build_batch_system_prompt,
    build_field_extraction_json_payload,
    build_field_extraction_request_prompt,
    build_field_extraction_system_prompt,
    is_narrative_field,
)
from ..schemas.field_extraction import (
    BatchFieldValueItem,
    BatchFieldValueResult,
    FieldValueResult,
)
from .extraction_service import _get_client
from .gemini_runtime_service import (
    GeminiTokenTracker,
    apply_thinking_config,
    get_or_create_ocr_prompt_cache,
    invalidate_ocr_prompt_cache,
    is_cached_content_error,
    record_usage_from_response,
)
from .rag_config import get_rag_settings
from ..utils.date_format import format_long_date, parse_date_text
from ..utils.text import clean_text as _clean_text

log = logging.getLogger("form_filling")

_BUTTON_TYPES = {"checkbox", "radio", "button"}
_CHOICE_TYPES = {"choice", "select", "combobox", "listbox"}
_BLANK_SENTINELS = {"", "null", "none", "n/a", "na", "unknown", "insufficient"}
_TRUE_SENTINELS = {"true", "1", "yes", "y", "checked", "check", "on", "x"}
_FALSE_SENTINELS = {"false", "0", "no", "n", "unchecked", "off"}
_A_NUMBER_RE = re.compile(r"^\d{1,9}$")
_OPENAI_DEFAULT_EXTRACTION_MODEL = "gpt-5.4"
_ANTHROPIC_DEFAULT_EXTRACTION_MODEL = "claude-sonnet-4-5-20250929"
_ANTHROPIC_MAX_OUTPUT_TOKENS = 2048


from .form_registry import normalize_form_type as _normalize_canonical_form_type  # noqa: E402


def _normalize_form_type(form_type: str = "") -> str:
    """Thin str-returning wrapper around the canonical normalizer."""
    return _normalize_canonical_form_type(form_type) or ""


def _field_id(field: Mapping[str, Any]) -> str:
    return _clean_text(field.get("id") or field.get("field_name"))


def _field_type(field: Mapping[str, Any]) -> str:
    return _clean_text(field.get("field_type") or field.get("field_type_hint") or "text").lower()


def _questionnaire_target_option(field: Mapping[str, Any]) -> str:
    return _clean_text(field.get("questionnaire_option_label") or field.get("questionnaire_option_value"))


def _questionnaire_options(field: Mapping[str, Any]) -> list[dict[str, str]]:
    raw_options = field.get("questionnaire_options") or field.get("options") or []
    normalized: list[dict[str, str]] = []
    if isinstance(raw_options, list):
        for option in raw_options:
            if isinstance(option, Mapping):
                value = _clean_text(option.get("value") or option.get("id") or option.get("label"))
                label = _clean_text(option.get("label") or option.get("value") or option.get("id"))
            else:
                value = _clean_text(option)
                label = value
            if value or label:
                normalized.append({"value": value or label, "label": label or value})
    return normalized


def _normalized_field_context(field: Mapping[str, Any]) -> str:
    return _clean_text(
        " ".join(
            str(part or "")
            for part in (
                field.get("id"),
                field.get("field_name"),
                field.get("field_label"),
                field.get("questionnaire_item_id"),
                field.get("questionnaire_field_id"),
                field.get("questionnaire_label"),
                field.get("questionnaire_form_text"),
                field.get("questionnaire_section"),
            )
        )
    ).lower()


def _is_a_number_field(field: Mapping[str, Any]) -> bool:
    context = _normalized_field_context(field)
    return "alien registration number" in context or "a-number" in context or ".a_number" in context


def _normalize_a_number(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    compact = "".join(ch for ch in text.upper() if ch.isalnum())
    if compact.startswith("A"):
        compact = compact[1:]
    return compact if _A_NUMBER_RE.fullmatch(compact) else ""


def _allowed_selection_values(field: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    field_type = _field_type(field)
    if field_type in _BUTTON_TYPES:
        keys = ("button_values",)
    elif field_type in _CHOICE_TYPES:
        keys = ("choice_values",)
    else:
        keys = ("button_values", "choice_values")

    for key in keys:
        raw_values = field.get(key) or []
        if isinstance(raw_values, Sequence) and not isinstance(raw_values, (str, bytes)):
            for value in raw_values:
                cleaned = _clean_text(value)
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)

    if not candidates:
        for option in _questionnaire_options(field):
            for value in (option.get("value"), option.get("label")):
                cleaned = _clean_text(value)
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)
    return candidates


def _match_allowed_value(value: str, allowed_values: list[str]) -> str:
    lowered = value.lower()
    for candidate in allowed_values:
        if candidate.lower() == lowered:
            return candidate
    return ""


def _normalize_date(value: str) -> str:
    """Normalize a free-form date string to canonical ``Mmm DD YYYY``.

    Falls back to the raw input when parsing fails so downstream callers can
    still inspect/repair the original text.
    """
    raw = _clean_text(value)
    if not raw:
        return ""
    parsed = parse_date_text(raw)
    if parsed is None:
        return raw
    return format_long_date(parsed)


def _normalize_value(field: Mapping[str, Any], value: Any) -> str:
    text = _clean_text(value)
    lowered = text.lower()
    if lowered in _BLANK_SENTINELS:
        return ""

    if _is_a_number_field(field):
        return _normalize_a_number(text)

    field_type = _field_type(field)
    target_option = _questionnaire_target_option(field)
    allowed_values = _allowed_selection_values(field)

    matched_option = _match_allowed_value(text, allowed_values)
    if matched_option:
        return matched_option

    if field_type == "date":
        return _normalize_date(text)

    if field_type in _BUTTON_TYPES:
        if target_option:
            if lowered == target_option.lower():
                return "true"
            if lowered in _TRUE_SENTINELS:
                return "true"
            if lowered in _FALSE_SENTINELS:
                return "false"
        if allowed_values:
            return text if text else ""
        if lowered in _TRUE_SENTINELS:
            return "true"
        if lowered in _FALSE_SENTINELS:
            return "false"
        return text

    if field_type in _CHOICE_TYPES:
        return text if text else ""

    if field_type == "signature":
        return ""

    return text


def _default_result(*, field_id: str = "") -> dict[str, str]:
    result = {
        "value": "",
        "confidence": "low",
        "justification": "",
    }
    if field_id:
        result["id"] = field_id
    return result


def _normalize_confidence(value: Any) -> str:
    lowered = _clean_text(value).lower()
    return lowered if lowered in {"high", "medium", "low"} else "low"


def _normalize_result(raw: Mapping[str, Any], field: Mapping[str, Any], *, include_id: bool = False) -> dict[str, str]:
    result = {
        "value": _normalize_value(field, raw.get("value", "")),
        "confidence": _normalize_confidence(raw.get("confidence", "low")),
        "justification": _clean_text(raw.get("justification", "")),
    }
    if include_id:
        result["id"] = _field_id(field)
    return result


def _get_openai_client():
    """Lazily create and return an OpenAI client for extraction experiments."""
    from openai import OpenAI

    settings = get_rag_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return OpenAI(api_key=settings.openai_api_key)


def _get_anthropic_client():
    """Lazily create and return an Anthropic client for extraction experiments."""
    import anthropic

    settings = get_rag_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _is_reasoning_model(model: str) -> bool:
    name = model.strip().lower()
    return (
        name.startswith("o1")
        or name.startswith("o3")
        or name.startswith("o4")
        or name.startswith("gpt-5")
    )


def _openai_model_supports_temperature(model: str) -> bool:
    return not _is_reasoning_model(model)


def _openai_max_completion_tokens(model: str, configured_max_tokens: int) -> int:
    if _is_reasoning_model(model):
        return max(configured_max_tokens, 16384)
    return configured_max_tokens


def _default_extraction_model(provider: str) -> str:
    if provider == "openai":
        return _OPENAI_DEFAULT_EXTRACTION_MODEL
    if provider == "anthropic":
        return _ANTHROPIC_DEFAULT_EXTRACTION_MODEL
    return get_rag_settings().gemini_model


def _select_extraction_model(
    provider: str,
    *,
    model_override: str | None = None,
) -> str:
    settings = get_rag_settings()
    if model_override:
        return model_override
    if settings.extraction_model:
        return settings.extraction_model
    return _default_extraction_model(provider)


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


def _parse_structured_response_text(
    raw_text: str,
    schema: type[BaseModel],
) -> dict[str, Any]:
    cleaned = _strip_json_fence(raw_text)
    decoder = json.JSONDecoder()
    last_validation_error: ValidationError | None = None
    for start in (idx for idx, char in enumerate(cleaned) if char == "{"):
        try:
            candidate, _ = decoder.raw_decode(cleaned[start:])
        except json.JSONDecodeError:
            continue
        try:
            parsed = schema.model_validate(candidate)
            return parsed.model_dump()
        except ValidationError as exc:
            last_validation_error = exc
            continue
    if last_validation_error is not None:
        raise last_validation_error
    parsed = schema.model_validate_json(cleaned)
    return parsed.model_dump()


def _evidence_has_content(evidence: Any) -> bool:
    if isinstance(evidence, Mapping):
        for key in ("text_context", "textContext"):
            if _clean_text(evidence.get(key)):
                return True
        for key in ("evidence", "matches"):
            value = evidence.get(key)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                return bool(value)
        return any(_clean_text(value) for value in evidence.values() if not isinstance(value, (dict, list)))
    if isinstance(evidence, Sequence) and not isinstance(evidence, (str, bytes)):
        return bool(evidence)
    text = _clean_text(evidence)
    return bool(text and text != "(no evidence available)")


def _extract_openai_message_text(response: Any) -> tuple[str, str]:
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


def _generate_structured_response_openai(
    contents: list[str],
    *,
    schema: type[BaseModel],
    model_override: str | None = None,
    max_output_tokens: int = 8192,
    temperature_override: float | None = None,
    step_label: str = "field-extract",
) -> dict[str, Any]:
    settings = get_rag_settings()
    client = _get_openai_client()
    model = _select_extraction_model("openai", model_override=model_override)
    kwargs: dict[str, Any] = {
        "model": model,
        "max_completion_tokens": _openai_max_completion_tokens(
            model,
            max(256, int(max_output_tokens or 8192)),
        ),
        "messages": [{"role": "user", "content": "\n\n".join(contents)}],
        "response_format": {"type": "json_object"},
    }
    if _openai_model_supports_temperature(model):
        kwargs["temperature"] = (
            temperature_override if temperature_override is not None else settings.verify_temperature
        )

    max_attempts = max(1, settings.verify_max_retries)
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        response = client.chat.completions.create(**kwargs)
        raw_text, response_detail = _extract_openai_message_text(response)
        if not raw_text:
            last_raw = response_detail
        else:
            try:
                return _parse_structured_response_text(raw_text, schema)
            except ValidationError:
                last_raw = raw_text[:1000]

        if attempt < max_attempts:
            log.warning(
                "[FORM_FILL] OpenAI parse error on attempt %d/%d for %s: %s",
                attempt,
                max_attempts,
                step_label,
                last_raw[:180],
            )

    return {"_parse_error": True, "_raw": last_raw}


def _generate_structured_response_anthropic(
    contents: list[str],
    *,
    schema: type[BaseModel],
    model_override: str | None = None,
    max_output_tokens: int = 8192,
    temperature_override: float | None = None,
    step_label: str = "field-extract",
) -> dict[str, Any]:
    settings = get_rag_settings()
    client = _get_anthropic_client()
    model = _select_extraction_model("anthropic", model_override=model_override)
    system_prompt = contents[0] if len(contents) > 1 else ""
    system_prompt = (
        f"{system_prompt}\n\n"
        "Return ONLY valid JSON matching the requested schema. "
        "Do not include analysis, markdown, code fences, or explanatory text.\n"
        "Return exactly one answer for every requested field id. Do not omit ids. "
        "If the evidence contains a direct or strongly consistent value, fill it and use "
        "confidence high or medium. Reserve confidence low for partial, conflicting, or "
        "insufficient evidence; empty values must use confidence low."
    ).strip()
    user_prompt = "\n\n".join(contents[1:] if len(contents) > 1 else contents)

    max_attempts = max(1, settings.verify_max_retries)
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        raw_chunks: list[str] = []
        with client.messages.stream(
            model=model,
            max_tokens=max(
                256,
                min(int(max_output_tokens or 8192), _ANTHROPIC_MAX_OUTPUT_TOKENS),
            ),
            temperature=temperature_override if temperature_override is not None else settings.verify_temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            for text in stream.text_stream:
                raw_chunks.append(text)
        raw_text = "".join(raw_chunks).strip()

        try:
            return _parse_structured_response_text(raw_text, schema)
        except ValidationError:
            last_raw = raw_text[:1000]
            if attempt < max_attempts:
                log.warning(
                    "[FORM_FILL] Anthropic parse error on attempt %d/%d for %s: %s",
                    attempt,
                    max_attempts,
                    step_label,
                    last_raw[:180],
                )

    return {"_parse_error": True, "_raw": last_raw}


def _generate_structured_response(
    contents: list[str],
    *,
    schema: type[BaseModel],
    model_override: str | None = None,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "field-extract",
    cached_content: str = "",
    max_output_tokens: int = 8192,
    temperature_override: float | None = None,
) -> dict[str, Any]:
    client = _get_client()
    settings = get_rag_settings()
    model = model_override or settings.gemini_model
    config_kwargs: dict[str, object] = {
        "temperature": temperature_override if temperature_override is not None else settings.verify_temperature,
        "max_output_tokens": max(256, int(max_output_tokens or 8192)),
        "response_mime_type": "application/json",
        "response_json_schema": schema.model_json_schema(),
    }
    apply_thinking_config(config_kwargs, settings.gemini_extraction_thinking_level)
    if cached_content:
        config_kwargs["cached_content"] = cached_content

    max_attempts = max(1, settings.verify_max_retries)
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        record_usage_from_response(
            tracker,
            step=f"{step_label}{'-retry' + str(attempt) if attempt > 1 else ''}",
            response=response,
            model=model,
        )

        raw_text = (response.text or "").strip()
        try:
            parsed = schema.model_validate_json(raw_text)
            return parsed.model_dump()
        except ValidationError:
            last_raw = raw_text[:1000]
            if attempt < max_attempts:
                log.warning(
                    "[FORM_FILL] Parse error on attempt %d/%d for %s: %s",
                    attempt,
                    max_attempts,
                    step_label,
                    last_raw[:180],
                )

    return {"_parse_error": True, "_raw": last_raw}


def _generate_structured_response_dispatch(
    contents: list[str],
    *,
    schema: type[BaseModel],
    model_override: str | None = None,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "field-extract",
    cached_content: str = "",
    max_output_tokens: int = 8192,
    temperature_override: float | None = None,
) -> dict[str, Any]:
    settings = get_rag_settings()
    provider = settings.extraction_provider
    if provider == "openai":
        return _generate_structured_response_openai(
            contents,
            schema=schema,
            model_override=model_override,
            max_output_tokens=max_output_tokens,
            temperature_override=temperature_override,
            step_label=step_label,
        )
    if provider == "anthropic":
        return _generate_structured_response_anthropic(
            contents,
            schema=schema,
            model_override=model_override,
            max_output_tokens=max_output_tokens,
            temperature_override=temperature_override,
            step_label=step_label,
        )
    gemini_model_override = model_override or settings.extraction_model or None
    return _generate_structured_response(
        contents,
        schema=schema,
        model_override=gemini_model_override,
        tracker=tracker,
        step_label=step_label,
        cached_content=cached_content,
        max_output_tokens=max_output_tokens,
        temperature_override=temperature_override,
    )


def extract_field_value(
    field: Mapping[str, Any],
    evidence: Any,
    *,
    form_type: str = "",
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "field-extract",
) -> dict[str, str]:
    """Extract a single field value from RAG evidence using Gemini."""
    request_prompt = build_field_extraction_request_prompt(
        build_field_extraction_json_payload(field=dict(field), evidence=evidence)
    )
    system_prompt = build_field_extraction_system_prompt(form_type)
    settings = get_rag_settings()
    temp = settings.narrative_temperature if is_narrative_field(field) else None
    contents = (
        [f"{system_prompt}\n\n{request_prompt}"]
        if settings.extraction_provider == "gemini"
        else [system_prompt, request_prompt]
    )
    raw = _generate_structured_response_dispatch(
        contents,
        schema=FieldValueResult,
        tracker=tracker,
        step_label=step_label,
        max_output_tokens=4096,
        temperature_override=temp,
    )
    if raw.get("_parse_error"):
        fallback = _default_result(field_id=_field_id(field))
        fallback["justification"] = _clean_text(raw.get("_raw", ""))
        fallback.pop("id", None)
        return fallback
    return _normalize_result(raw, field)


def extract_field_values_batch(
    fields: Sequence[Mapping[str, Any]],
    evidence_by_id: Mapping[str, Any],
    *,
    form_type: str = "",
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "field-extract-batch",
    applicant_context: str = "",
) -> list[dict[str, str]]:
    """
    Extract multiple field values in a single Gemini call.

    ``fields`` must contain an ``id`` or ``field_name`` for each item.
    ``evidence_by_id`` maps that id to either a retrieval bundle, structured evidence list, or text.
    """
    normalized_fields = [dict(field) for field in fields]
    if not normalized_fields:
        return []

    settings = get_rag_settings()
    is_gemini_provider = settings.extraction_provider == "gemini"
    batch_model = (
        _select_extraction_model("gemini", model_override=settings.qc_batch_model)
        if is_gemini_provider
        else _select_extraction_model(settings.extraction_provider)
    )
    has_narrative = any(is_narrative_field(f) for f in normalized_fields)
    batch_temp = settings.narrative_temperature if has_narrative else None
    request_prompt = build_batch_request_prompt(
        build_field_extraction_batch_json_payload(
            normalized_fields, dict(evidence_by_id),
            applicant_context=applicant_context,
        )
    )
    system_prompt = build_batch_system_prompt(form_type)

    normalized_form = _normalize_form_type(form_type) or "default"
    cached_content = ""
    if is_gemini_provider and settings.qc_batch_use_prompt_cache:
        client = _get_client()
        cached_content = get_or_create_ocr_prompt_cache(
            client,
            model=batch_model,
            prompt_profile=f"form-fill-batch-{normalized_form}-v2",
            system_prompt=system_prompt,
            placeholder_text=FORM_FILL_CACHE_PLACEHOLDER,
        )

    if cached_content:
        contents = [request_prompt]
    elif is_gemini_provider:
        contents = [f"{system_prompt}\n\n{request_prompt}"]
    else:
        contents = [system_prompt, request_prompt]

    try:
        raw = _generate_structured_response_dispatch(
            contents,
            schema=BatchFieldValueResult,
            model_override=batch_model,
            tracker=tracker,
            step_label=step_label,
            cached_content=cached_content,
            max_output_tokens=settings.qc_batch_max_output_tokens,
            temperature_override=batch_temp,
        )
    except Exception as exc:
        if is_gemini_provider and cached_content and is_cached_content_error(exc):
            invalidate_ocr_prompt_cache(cached_content)
            log.warning(
                "[FORM_FILL] Cached batch prompt invalid for form=%s. Retrying without cache: %s",
                normalized_form,
                str(exc),
            )
            raw = _generate_structured_response_dispatch(
                [f"{system_prompt}\n\n{request_prompt}"],
                schema=BatchFieldValueResult,
                model_override=batch_model,
                tracker=tracker,
                step_label=step_label,
                max_output_tokens=settings.qc_batch_max_output_tokens,
                temperature_override=batch_temp,
            )
        else:
            raise

    if raw.get("_parse_error"):
        return [_default_result(field_id=_field_id(field)) for field in normalized_fields]

    answers_raw = raw.get("answers", [])
    if not isinstance(answers_raw, list):
        return [_default_result(field_id=_field_id(field)) for field in normalized_fields]

    fields_by_id = {_field_id(field): field for field in normalized_fields}
    answers_by_id: dict[str, dict[str, str]] = {}
    for answer in answers_raw:
        if not isinstance(answer, Mapping):
            continue
        answer_id = _clean_text(answer.get("id"))
        field = fields_by_id.get(answer_id)
        if not field:
            continue
        normalized = _normalize_result(answer, field, include_id=True)
        answers_by_id[answer_id] = normalized

    ordered: list[dict[str, str]] = []
    for field in normalized_fields:
        field_id = _field_id(field)
        ordered.append(answers_by_id.get(field_id, _default_result(field_id=field_id)))
    if settings.extraction_provider == "anthropic":
        evidence_backed_count = sum(
            1
            for field in normalized_fields
            if _evidence_has_content(evidence_by_id.get(_field_id(field)))
        )
        usable_count = sum(
            1
            for item in ordered
            if _clean_text(item.get("value")) and _normalize_confidence(item.get("confidence")) in {"high", "medium"}
        )
        min_usable = max(1, evidence_backed_count // 5)
        if evidence_backed_count >= 3 and usable_count < min_usable:
            raise RuntimeError(
                "Anthropic batch extraction returned too few usable values "
                f"({usable_count}/{evidence_backed_count}); falling back to single-field extraction."
            )
    return ordered


class _ReasonParaphraseResult(BaseModel):
    reason: str = Field(description="Concise paraphrased reason, max 2 short sentences.")


_REASON_PARAPHRASE_SYSTEM_PROMPT = (
    "You rewrite the 'reason' field of a single Part 9 addendum entry for USCIS Form I-914.\n"
    "Hard rules (never violate):\n"
    "- Return JSON matching the provided schema.\n"
    "- Output MUST be at most two short sentences and under 220 characters total.\n"
    "- Never invent facts not in the raw text.\n"
    "- Do NOT use the phrase 'law enforcement' when authority_kind is 'immigration'. "
    "  Use CBP, ICE, DHS, immigration authorities, border authorities, or immigration officers instead.\n"
    "- Do NOT escalate the event category. If the input is IMMIGRATION_DETENTION, never reword "
    "  it as an arrest, charge, conviction, removal order, deportation, or denial of admission.\n"
    "- If the raw text is insufficient, return an empty reason string.\n"
    "- Write in plain English, neutral and conservative tone."
)


def paraphrase_reason_slot(
    raw_text: str,
    *,
    authority_kind: str = "unknown",
    category: str = "",
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "i914-reason-paraphrase",
) -> str:
    """Controlled LLM paraphrase for the ``{reason}`` slot in I-914 Part 9.

    Invoked by the deterministic template builder only when the extracted reason
    is missing or too generic. The prompt is tiny and heavily constrained so the
    LLM cannot escalate the event category nor invent authorities.

    Returns the paraphrased text, or an empty string when the LLM cannot parse
    a useful reason. Callers must fall back to the conservative boilerplate
    (``"the reason remains to be confirmed (if known)"``) when the result is
    empty.
    """
    cleaned_raw = _clean_text(raw_text)
    if not cleaned_raw:
        return ""

    normalized_authority = _clean_text(authority_kind).lower() or "unknown"
    if normalized_authority not in {"immigration", "criminal", "unknown"}:
        normalized_authority = "unknown"
    normalized_category = _clean_text(category).lower()

    user_prompt = (
        f"authority_kind: {normalized_authority}\n"
        f"category: {normalized_category or 'unknown'}\n"
        f"raw_text (verbatim evidence snippet, do not invent beyond it):\n"
        f"{cleaned_raw[:800]}\n\n"
        "Return JSON with a single 'reason' field. Preserve dates and places only "
        "if they already appear in the raw text."
    )

    raw = _generate_structured_response(
        [f"{_REASON_PARAPHRASE_SYSTEM_PROMPT}\n\n{user_prompt}"],
        schema=_ReasonParaphraseResult,
        tracker=tracker,
        step_label=step_label,
        max_output_tokens=256,
    )
    if raw.get("_parse_error"):
        return ""
    reason = _clean_text(raw.get("reason", ""))
    if len(reason) > 260:
        reason = reason[:257].rstrip() + "..."
    return reason

