"""
AI Verification Service -- uses Gemini to verify QC checklist questions.

Supports three modes:
  1) Image + text  (vision model, page images + OCR context)
  2) Text-only RAG (text model, Gemini OCR evidence only, no images)
  3) Batch RAG     (text model, multiple questions with per-question evidence)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import PIL.Image
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from .extraction_service import _get_client
from .gemini_runtime_service import (
    GeminiTokenTracker,
    get_or_create_ocr_prompt_cache,
    invalidate_ocr_prompt_cache,
    is_cached_content_error,
    record_usage_from_response,
)
from .rag_config import get_rag_settings
from ..prompts import (
    OCR_MARKERS_INSTRUCTIONS,
    VERIFY_CACHE_PLACEHOLDER,
    VERIFY_PROMPT,
    build_rag_batch_toon_payload,
    build_rag_batch_request_prompt,
    build_rag_batch_system_prompt,
    build_rag_verify_request_prompt,
    build_rag_verify_system_prompt,
    build_rag_verify_toon_payload,
    get_form_context,
)

from .paths import STORAGE_DIR

log = logging.getLogger("qc_autopilot")


# ---------------------------------------------------------------------------
# Schema models (sent to Gemini as response_json_schema)
# ---------------------------------------------------------------------------
_DECISION_LITERAL = Literal["YES", "NO", "INSUFFICIENT"]


class VerificationResult(BaseModel):
    decision: _DECISION_LITERAL = Field(
        description="YES if correct or present, NO if error or inconsistent, INSUFFICIENT only if absolutely no related information exists."
    )
    justification: str = Field(
        description="Short justification referencing specific evidence and page numbers used."
    )
    correction: str = Field(
        description="Required correction when decision is NO, otherwise an empty string."
    )


class BatchAnswerItem(BaseModel):
    id: str = Field(description="Question identifier.")
    decision: _DECISION_LITERAL = Field(
        description="YES if correct or present, NO if error or inconsistent, INSUFFICIENT only if absolutely no related information exists."
    )
    justification: str = Field(
        description="Short justification referencing specific evidence and page numbers used."
    )
    correction: str = Field(description="Correction if decision is NO, else empty.")


class BatchVerificationResult(BaseModel):
    answers: list[BatchAnswerItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_CONFIDENCE_FROM_DECISION = {"YES": "high", "NO": "high", "INSUFFICIENT": "medium"}


def _normalize_result(raw: dict) -> dict:
    """Map Gemini's simplified schema back to the legacy dict shape expected by callers."""
    decision = str(raw.get("decision", "INSUFFICIENT")).upper()
    if decision not in ("YES", "NO", "INSUFFICIENT"):
        decision = "INSUFFICIENT"
    justification = str(raw.get("justification", "") or "").strip()
    confidence = _CONFIDENCE_FROM_DECISION.get(decision, "low")
    if decision == "INSUFFICIENT" and not justification:
        confidence = "low"
    return {
        "answer": decision.lower(),
        "confidence": confidence,
        "explanation": justification,
        "correction": str(raw.get("correction", "") or "").strip(),
    }


def _default_result(*, rag_mode: bool = False) -> dict:
    return {
        "answer": "insufficient",
        "confidence": "low",
        "explanation": "",
        "correction": "",
    }


def _generate_structured_response(
    contents: list,
    *,
    model_override: str | None = None,
    schema: type[BaseModel] = VerificationResult,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "verify",
    rag_mode: bool = False,
    cached_content: str = "",
    max_output_tokens: int = 65536,
) -> dict:
    client = _get_client()
    settings = get_rag_settings()
    model = model_override or settings.gemini_vision_model or settings.gemini_model
    config_kwargs: dict[str, object] = {
        "temperature": settings.verify_temperature,
        "max_output_tokens": max(128, int(max_output_tokens or 65536)),
        "response_mime_type": "application/json",
        "response_json_schema": schema.model_json_schema(),
    }
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
            last_raw = raw_text[:500]
            if attempt < max_attempts:
                log.warning(
                    "[VERIFY] Parse error on attempt %d/%d, retrying: %s",
                    attempt, max_attempts, last_raw[:120],
                )

    return {"_parse_error": True, "_raw": last_raw}


# ---------------------------------------------------------------------------
# Mode 1: Image-based (existing)
# ---------------------------------------------------------------------------
def verify_question(
    image_path: str,
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "verify-image",
) -> dict:
    """Send a page image + QC question to Gemini Vision."""
    img = PIL.Image.open(image_path)
    prompt = VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
        text_context=text_context or "No OCR context retrieved.",
        form_context=get_form_context(form_type),
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )
    raw = _generate_structured_response(
        [prompt, img],
        tracker=tracker,
        step_label=step_label,
    )
    if raw.get("_parse_error"):
        fallback = _default_result()
        fallback["explanation"] = raw.get("_raw", "")
        return fallback
    return _normalize_result(raw)


def verify_question_multi_page(
    image_paths: list[str],
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "verify-image-multi",
) -> dict:
    """Verify a question against multiple page images at once."""
    contents: list = [
        VERIFY_PROMPT.format(
            question=question_text,
            where_to_verify=where_to_verify or "Not specified",
            text_context=text_context or "No OCR context retrieved.",
            form_context=get_form_context(form_type),
            ocr_markers=OCR_MARKERS_INSTRUCTIONS,
        )
    ]
    for path in image_paths[:5]:
        contents.append(PIL.Image.open(path))
    raw = _generate_structured_response(
        contents,
        tracker=tracker,
        step_label=step_label,
    )
    if raw.get("_parse_error"):
        fallback = _default_result()
        fallback["explanation"] = raw.get("_raw", "")
        return fallback
    return _normalize_result(raw)


# ---------------------------------------------------------------------------
# Mode 2: Text-only RAG
# ---------------------------------------------------------------------------
def verify_question_rag(
    question_text: str,
    where_to_verify: str,
    text_evidence: str,
    form_type: str = "",
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "verify-rag",
) -> dict:
    """Verify a QC question using only OCR text evidence (no images)."""
    settings = get_rag_settings()
    system_prompt = build_rag_verify_system_prompt(form_type)
    request_prompt = build_rag_verify_request_prompt(
        build_rag_verify_toon_payload(
            question_text=question_text,
            where_to_verify=where_to_verify,
            text_evidence=text_evidence,
        )
    )
    raw = _generate_structured_response(
        [f"{system_prompt}\n\n{request_prompt}"],
        model_override=settings.gemini_model,
        schema=VerificationResult,
        tracker=tracker,
        step_label=step_label,
        rag_mode=True,
    )
    if raw.get("_parse_error"):
        fallback = _default_result(rag_mode=True)
        fallback["explanation"] = raw.get("_raw", "")
        return fallback
    return _normalize_result(raw)


# ---------------------------------------------------------------------------
# Mode 3: Batch RAG (per-question evidence, like OCRDocPinecone)
# ---------------------------------------------------------------------------
def verify_question_batch_rag(
    questions: list[dict],
    evidence_by_id: dict[str, str],
    form_type: str = "",
    *,
    tracker: GeminiTokenTracker | None = None,
    step_label: str = "verify-batch-rag",
) -> list[dict]:
    """
    Verify multiple QC questions in a single Gemini call.

    ``questions`` is a list of dicts with keys: id, description, where_to_verify.
    ``evidence_by_id`` maps question id -> formatted text evidence for that question.
    Returns a list of dicts with keys: id, answer, confidence, explanation, correction.
    """
    settings = get_rag_settings()
    use_prompt_cache = settings.qc_batch_use_prompt_cache
    batch_model = settings.qc_batch_model or settings.gemini_model
    fast_batch_prompt = settings.qc_batch_fast_prompt
    batch_max_output_tokens = settings.qc_batch_max_output_tokens

    normalized_form = form_type.strip().lower().replace(" ", "-") if form_type else "default"
    system_prompt = build_rag_batch_system_prompt(form_type)
    request_prompt = build_rag_batch_request_prompt(
        build_rag_batch_toon_payload(questions, evidence_by_id)
    )
    client = _get_client()
    cached_content = ""
    if use_prompt_cache:
        cached_content = get_or_create_ocr_prompt_cache(
            client,
            model=batch_model,
            prompt_profile=f"verify-batch-rag-{normalized_form}-fast{1 if fast_batch_prompt else 0}-v3",
            system_prompt=system_prompt,
            placeholder_text=VERIFY_CACHE_PLACEHOLDER,
        )
    contents = [request_prompt] if cached_content else [f"{system_prompt}\n\n{request_prompt}"]

    try:
        result = _generate_structured_response(
            contents,
            model_override=batch_model,
            schema=BatchVerificationResult,
            tracker=tracker,
            step_label=step_label,
            rag_mode=True,
            cached_content=cached_content,
            max_output_tokens=batch_max_output_tokens,
        )
    except Exception as exc:
        if cached_content and is_cached_content_error(exc):
            invalidate_ocr_prompt_cache(cached_content)
            log.warning(
                "[GEMINI] Verification cached content invalid for form=%s. Retrying without cache: %s",
                normalized_form,
                str(exc),
            )
            result = _generate_structured_response(
                [f"{system_prompt}\n\n{request_prompt}"],
                model_override=batch_model,
                schema=BatchVerificationResult,
                tracker=tracker,
                step_label=step_label,
                rag_mode=True,
                max_output_tokens=batch_max_output_tokens,
            )
        else:
            raise

    if result.get("_parse_error"):
        return [_default_result(rag_mode=True) | {"id": q.get("id", "")} for q in questions]

    answers_raw = result.get("answers", [])
    if not isinstance(answers_raw, list):
        return [_default_result(rag_mode=True) | {"id": q.get("id", "")} for q in questions]

    answers_by_id: dict[str, dict] = {}
    for ans in answers_raw:
        if isinstance(ans, dict) and "id" in ans:
            normalized = _normalize_result(ans)
            normalized["id"] = ans["id"]
            answers_by_id[ans["id"]] = normalized

    ordered: list[dict] = []
    for q in questions:
        qid = q.get("id", "")
        if qid in answers_by_id:
            ordered.append(answers_by_id[qid])
        else:
            ordered.append(_default_result(rag_mode=True) | {"id": qid})
    return ordered
