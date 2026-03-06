"""
AI Verification Service -- uses Gemini to verify QC checklist questions.

Supports three modes:
  1) Image + text  (vision model, page images + OCR context)
  2) Text-only RAG (text model, Gemini OCR evidence only, no images)
  3) Batch RAG     (text model, multiple questions with per-question evidence)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import PIL.Image
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from .extraction_service import _get_client
from .rag_config import get_rag_settings
from ..prompts import (
    FORM_CONTEXT,
    COMMON_VERIFICATION_SOURCES,
    OCR_MARKERS_INSTRUCTIONS,
    VERIFY_PROMPT,
    RAG_VERIFY_PROMPT,
    RAG_BATCH_PROMPT,
    get_form_context,
)

log = logging.getLogger("qc_autopilot")

STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"


# ---------------------------------------------------------------------------
# Schema models
# ---------------------------------------------------------------------------
_ANSWER_LITERAL = Literal["yes", "no", "na", "insufficient"]
_CONFIDENCE_LITERAL = Literal["high", "medium", "low"]


class VerificationResult(BaseModel):
    answer: _ANSWER_LITERAL = Field(
        description="Final QC decision based on the document evidence."
    )
    confidence: _CONFIDENCE_LITERAL = Field(
        description="Confidence level for the QC decision."
    )
    explanation: str = Field(
        description="Short explanation referencing the evidence found in the document."
    )
    correction: str = Field(
        description="Required correction when answer is no, otherwise an empty string."
    )


class BatchAnswerItem(BaseModel):
    id: str = Field(description="Question identifier.")
    answer: _ANSWER_LITERAL = Field(description="QC decision.")
    confidence: _CONFIDENCE_LITERAL = Field(description="Confidence level.")
    explanation: str = Field(description="Short explanation referencing evidence.")
    correction: str = Field(description="Correction if answer is no, else empty.")


class BatchVerificationResult(BaseModel):
    answers: list[BatchAnswerItem]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _default_result(*, rag_mode: bool = False) -> dict:
    return {
        "answer": "insufficient" if rag_mode else "na",
        "confidence": "low",
        "explanation": "",
        "correction": "",
    }


def _generate_structured_response(
    contents: list,
    *,
    model_override: str | None = None,
    schema: type[BaseModel] = VerificationResult,
) -> dict:
    client = _get_client()
    settings = get_rag_settings()
    model = model_override or settings.gemini_vision_model or settings.gemini_model
    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=4096,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        ),
    )

    raw_text = (response.text or "").strip()
    try:
        result = schema.model_validate_json(raw_text)
        return result.model_dump()
    except ValidationError:
        fallback = _default_result()
        fallback["explanation"] = raw_text[:500]
        return fallback


# ---------------------------------------------------------------------------
# Mode 1: Image-based (existing)
# ---------------------------------------------------------------------------
def verify_question(
    image_path: str,
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
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
    return _generate_structured_response([prompt, img])


def verify_question_multi_page(
    image_paths: list[str],
    question_text: str,
    where_to_verify: str,
    text_context: str = "",
    form_type: str = "",
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
    return _generate_structured_response(contents)


# ---------------------------------------------------------------------------
# Mode 2: Text-only RAG
# ---------------------------------------------------------------------------
def verify_question_rag(
    question_text: str,
    where_to_verify: str,
    text_evidence: str,
    form_type: str = "",
) -> dict:
    """Verify a QC question using only OCR text evidence (no images)."""
    settings = get_rag_settings()
    prompt = RAG_VERIFY_PROMPT.format(
        question=question_text,
        where_to_verify=where_to_verify or "Not specified",
        text_evidence=text_evidence,
        form_context=get_form_context(form_type),
        common_sources=COMMON_VERIFICATION_SOURCES,
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )
    return _generate_structured_response(
        [prompt],
        model_override=settings.gemini_model,
        schema=VerificationResult,
    )


# ---------------------------------------------------------------------------
# Mode 3: Batch RAG (per-question evidence, like OCRDocPinecone)
# ---------------------------------------------------------------------------
def verify_question_batch_rag(
    questions: list[dict],
    evidence_by_id: dict[str, str],
    form_type: str = "",
) -> list[dict]:
    """
    Verify multiple QC questions in a single Gemini call.

    ``questions`` is a list of dicts with keys: id, description, where_to_verify.
    ``evidence_by_id`` maps question id -> formatted text evidence for that question.
    Returns a list of dicts with keys: id, answer, confidence, explanation, correction.
    """
    settings = get_rag_settings()

    lines: list[str] = []
    for q in questions:
        qid = q.get("id", "")
        desc = q.get("description", "")
        where = q.get("where_to_verify", "")
        evidence = evidence_by_id.get(qid, "")
        lines.append(f"[{qid}] {desc}")
        if where:
            lines.append(f"    Where to verify: {where}")
        lines.append("    Evidence:")
        if evidence.strip():
            for ev_line in evidence.strip().splitlines():
                lines.append(f"    {ev_line}")
        else:
            lines.append("    (no evidence available)")
        lines.append("")
    questions_block = "\n".join(lines)

    prompt = RAG_BATCH_PROMPT.format(
        questions_block=questions_block,
        form_context=get_form_context(form_type),
        common_sources=COMMON_VERIFICATION_SOURCES,
        ocr_markers=OCR_MARKERS_INSTRUCTIONS,
    )

    result = _generate_structured_response(
        [prompt],
        model_override=settings.gemini_model,
        schema=BatchVerificationResult,
    )

    answers_raw = result.get("answers", [])
    if not isinstance(answers_raw, list):
        return [_default_result(rag_mode=True) | {"id": q.get("id", "")} for q in questions]

    answers_by_id: dict[str, dict] = {}
    for ans in answers_raw:
        if isinstance(ans, dict) and "id" in ans:
            answers_by_id[ans["id"]] = ans

    ordered: list[dict] = []
    for q in questions:
        qid = q.get("id", "")
        if qid in answers_by_id:
            ordered.append(answers_by_id[qid])
        else:
            ordered.append(_default_result(rag_mode=True) | {"id": qid})
    return ordered
