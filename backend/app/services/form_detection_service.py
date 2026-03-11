"""
Automatic form type detection ported from v1 (formDetector.service.js).

Two-stage approach per document:
  1. Fast keyword matching against first 5 pages of OCR text
  2. LLM fallback via Gemini if keywords are inconclusive

Results are cached per source_document_id for the lifetime of a job.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..prompts.form_detection_prompts import FORM_DETECTOR_PROMPT

log = logging.getLogger("qc_autopilot")

SUPPORTED_FORM_TYPES = {"i-914", "i-914a"}

_KNOWN_FORMS: list[dict[str, Any]] = [
    {
        "type": "i-914a",
        "keywords": [
            re.compile(r"supplement\s*a", re.IGNORECASE),
            re.compile(r"i[- ]?914\s*a\b", re.IGNORECASE),
            re.compile(r"i[- ]?914,?\s*supplement", re.IGNORECASE),
            re.compile(r"derivative\s+t\s+nonimmigrant", re.IGNORECASE),
            re.compile(r"application\s+for\s+derivative\s+t", re.IGNORECASE),
        ],
        "priority": 10,
    },
    {
        "type": "i-914",
        "keywords": [
            re.compile(r"form\s+i[- ]?914\b", re.IGNORECASE),
            re.compile(r"i[- ]?914\b", re.IGNORECASE),
            re.compile(r"application\s+for\s+t\s+nonimmigrant\s+status", re.IGNORECASE),
            re.compile(r"t\s+nonimmigrant\s+status", re.IGNORECASE),
        ],
        "priority": 5,
    },
]


def _score_by_keywords(text: str, form_def: dict[str, Any]) -> int:
    hits = 0
    for regex in form_def["keywords"]:
        hits += len(regex.findall(text))
    return hits


def _normalize_form_code(raw: str) -> str:
    compact = re.sub(r"^form\s+", "", raw.strip().lower())
    compact = re.sub(r"^i[\s-]?", "", compact)
    compact = re.sub(r"\s+", "", compact)
    if not compact:
        return ""
    return f"i-{compact}"


def _extract_explicit_form_code(text: str) -> str:
    if not text:
        return ""
    if re.search(r"i[- ]?914\s*,?\s*supplement\s*a", text, re.IGNORECASE):
        return "i-914a"
    explicit = re.findall(r"\bform\s+i[-\s]?(\d{2,4}[a-z]?)\b", text, re.IGNORECASE)
    if explicit:
        return _normalize_form_code(explicit[0])
    return ""


def _detect_by_keywords(text: str) -> dict[str, str] | None:
    scores = [
        {"type": fd["type"], "score": _score_by_keywords(text, fd), "priority": fd["priority"]}
        for fd in _KNOWN_FORMS
    ]
    scores.sort(key=lambda s: (-s["score"], -s["priority"]))
    if scores[0]["score"] == 0:
        return None

    if scores[0]["type"] == "i-914" and len(scores) > 1:
        i914a = next((s for s in scores if s["type"] == "i-914a"), None)
        if i914a and i914a["score"] > 0:
            return {
                "form_type": "i-914a",
                "detection_source": "keyword",
                "reason": "Detected Supplement A markers in document text.",
            }

    return {
        "form_type": scores[0]["type"],
        "detection_source": "keyword",
        "reason": "Detected supported template keywords in document text.",
    }


def _detect_by_llm(text: str) -> dict[str, str]:
    truncated = text[:4000]
    prompt = f"{FORM_DETECTOR_PROMPT}{truncated}"

    try:
        from .gemini_runtime_service import create_token_tracker
        from .ai_verify_service import _get_client

        client = _get_client()
        from .rag_config import get_rag_settings
        settings = get_rag_settings()

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=[prompt],
        )
        import json
        raw_text = response.text or ""
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"```\s*$", "", cleaned)

        result = json.loads(cleaned)
        raw_type = str(result.get("formType", "") or "").strip().lower()
        reason = str(result.get("reason", "") or "").strip()

        if raw_type in SUPPORTED_FORM_TYPES:
            return {
                "form_type": raw_type,
                "detection_source": "llm",
                "reason": reason or f"LLM classified document as {raw_type.upper()}.",
            }

        if raw_type == "unsupported":
            return {
                "form_type": "unsupported",
                "detection_source": "llm",
                "reason": reason or "Detected unsupported USCIS form.",
            }

        return {
            "form_type": "supporting",
            "detection_source": "llm",
            "reason": reason or "Classified as supporting evidence document.",
        }
    except Exception as exc:
        log.warning("LLM form detection failed, defaulting to supporting: %s", exc)
        return {
            "form_type": "supporting",
            "detection_source": "llm-fallback",
            "reason": "Detection fallback: could not classify form with LLM.",
        }


def detect_form_type_from_text(combined_text: str) -> dict[str, str]:
    """
    Detect form type from combined OCR text using v1's two-stage approach.
    Returns dict with keys: form_type, detection_source, reason.
    """
    if not combined_text or len(combined_text.strip()) < 20:
        return {
            "form_type": "supporting",
            "detection_source": "insufficient-text",
            "reason": "Insufficient OCR text to determine a template form.",
        }

    keyword_result = _detect_by_keywords(combined_text)
    if keyword_result:
        return keyword_result

    explicit_code = _extract_explicit_form_code(combined_text)
    if explicit_code:
        if explicit_code in SUPPORTED_FORM_TYPES:
            return {
                "form_type": explicit_code,
                "detection_source": "explicit-form-code",
                "reason": "Detected explicit supported USCIS form code in document.",
            }
        return {
            "form_type": "unsupported",
            "detection_source": "explicit-form-code",
            "reason": f"Detected USCIS form {explicit_code.upper()}, but no template is configured.",
        }

    return _detect_by_llm(combined_text)


def detect_form_type_for_document(
    source_document_id: str,
    case_id: str,
    *,
    max_pages: int = 5,
) -> dict[str, str]:
    """
    Detect form type for a source document by scanning its first N pages' OCR text.
    """
    from ..database import SessionLocal
    from ..models import Page

    db = SessionLocal()
    try:
        pages = (
            db.query(Page)
            .filter(
                Page.case_id == case_id,
                Page.source_document_id == source_document_id,
                Page.ocr_text.isnot(None),
            )
            .order_by(Page.original_page_number.asc())
            .limit(max_pages)
            .all()
        )
        combined = " ".join((p.ocr_text or "").strip() for p in pages if p.ocr_text)
        return detect_form_type_from_text(combined)
    finally:
        db.close()


class FormTypeCache:
    """Per-job cache of form type detection results keyed by source_document_id."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, str]] = {}

    def get_or_detect(
        self,
        source_document_id: str | None,
        case_id: str,
    ) -> str:
        """Return the form_type string, using cache when available."""
        if not source_document_id:
            return ""

        if source_document_id in self._cache:
            return self._cache[source_document_id].get("form_type", "")

        result = detect_form_type_for_document(source_document_id, case_id)
        self._cache[source_document_id] = result
        form_type = result.get("form_type", "")
        log.info(
            "Form detection [%s]: %s (source=%s)",
            source_document_id[:8],
            form_type,
            result.get("detection_source", ""),
        )
        if form_type not in SUPPORTED_FORM_TYPES:
            return ""
        return form_type

    def clear(self) -> None:
        self._cache.clear()
