from __future__ import annotations

import logging
import re
from typing import Any

from .checklist_index_service import query_checklist_answers
from .gemini_runtime_service import GeminiTokenTracker
from .ocr_index_service import query_ocr_chunks
from .pinecone_client import is_pinecone_configured
from .rag_config import get_rag_settings

log = logging.getLogger("qc_autopilot")

# ---------------------------------------------------------------------------
# Evidence ranking (ported from OCRDocPinecone checklistFiller.service.js)
# ---------------------------------------------------------------------------
_SELECTION_CUE_RE = re.compile(
    r"[\u2611\u2612]|\[x\]|\(x\)|\bchecked\b|\bselected\b|\bmarcado\b",
    re.IGNORECASE,
)
_YES_NO_RE = re.compile(r"\bYes\s+No\b", re.IGNORECASE)


def _evidence_rank_score(match: dict[str, Any]) -> float:
    score = float(match.get("score", 0))
    metadata = match.get("metadata", {}) or {}
    text = str(metadata.get("text", ""))
    source_type = str(metadata.get("source_type", ""))

    if _SELECTION_CUE_RE.search(text):
        score += 0.4
    if _YES_NO_RE.search(text):
        score += 0.05
    if source_type.startswith("gemini"):
        score += 0.08
    return score


def _dedup_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for match in matches:
        metadata = match.get("metadata", {}) or {}
        page_id = str(metadata.get("page_id", ""))
        chunk_order = str(metadata.get("chunk_order", "0"))
        text = str(metadata.get("text", ""))[:80]
        key = f"{page_id}:{chunk_order}:{text}"
        existing = seen.get(key)
        if not existing or float(match.get("score", 0)) > float(existing.get("score", 0)):
            seen[key] = match
    return list(seen.values())


def format_match_context(matches: list[dict[str, Any]], *, max_chars: int = 4000) -> str:
    ranked = sorted(matches, key=_evidence_rank_score, reverse=True)
    blocks: list[str] = []
    remaining = max_chars

    for idx, match in enumerate(ranked, start=1):
        metadata = match.get("metadata", {}) or {}
        label = metadata.get("section_path_code") or metadata.get("question_code") or metadata.get("page_id") or "match"
        text = metadata.get("text") or metadata.get("explanation") or metadata.get("question") or ""
        snippet = str(text).strip()
        if not snippet:
            continue

        block = f"[{idx}] {label}\n{snippet}"
        if len(block) > remaining:
            block = block[: max(0, remaining)].rstrip()
        if not block:
            break
        blocks.append(block)
        remaining -= len(block) + 2
        if remaining <= 0:
            break

    return "\n\n".join(blocks)


def _ocr_text_from_db(case_id: str, *, max_chars: int = 6000) -> str:
    """Fallback: gather Gemini OCR text directly from the DB when Pinecone is not available."""
    from ..database import SessionLocal
    from ..models import Page

    db = SessionLocal()
    try:
        pages = (
            db.query(Page)
            .filter(Page.case_id == case_id, Page.ocr_text.isnot(None))
            .order_by(Page.created_at.asc())
            .all()
        )
        blocks: list[str] = []
        remaining = max_chars
        for pg in pages:
            text = (pg.ocr_text or "").strip()
            if not text:
                continue
            label = pg.original_filename or pg.id[:8]
            block = f"--- Page {pg.original_page_number} ({label}) ---\n{text}"
            if len(block) > remaining:
                block = block[:remaining].rstrip()
            if not block:
                break
            blocks.append(block)
            remaining -= len(block) + 2
            if remaining <= 0:
                break
        return "\n\n".join(blocks)
    finally:
        db.close()


def collect_evidence_for_question(
    question_text: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> str:
    """
    Collect, rank, dedup, and format evidence for a single QC question.
    Merges results from all retrieval stages (like OCRDocPinecone collectEvidence).
    Returns formatted text evidence string.
    """
    settings = get_rag_settings()
    resolved_top_k = max(4, top_k or settings.retrieval_top_k)

    if is_pinecone_configured():
        all_matches: list[dict[str, Any]] = []
        evidence_page_ids = [str(pid) for pid in (evidence_page_ids or []) if pid]
        target_section_ids = [str(sid) for sid in (target_section_ids or []) if sid]

        stages: list[tuple[str, dict[str, Any]]] = []
        if evidence_page_ids:
            stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
        if target_section_ids:
            stages.append(("target_sections", {"section_ids": target_section_ids}))
        stages.append(("case_wide", {}))

        for stage_name, extra_filters in stages:
            try:
                matches = query_ocr_chunks(
                    question_text,
                    case_id=case_id,
                    top_k=resolved_top_k,
                    tracker=tracker,
                    step_label=f"evidence-query-{stage_name}",
                    **extra_filters,
                )
                all_matches.extend(matches)
            except Exception as exc:
                log.warning("Evidence query failed (stage=%s): %s", stage_name, exc)

        if all_matches:
            deduped = _dedup_matches(all_matches)
            ranked = sorted(deduped, key=_evidence_rank_score, reverse=True)
            return format_match_context(ranked[:resolved_top_k])

    db_text = _ocr_text_from_db(case_id)
    return db_text


def retrieve_qc_text_context(
    question: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    """
    Get text context for a QC question.
    Priority: Pinecone semantic search -> DB ocr_text fallback.
    """
    if is_pinecone_configured():
        evidence_page_ids = [str(pid) for pid in (evidence_page_ids or []) if pid]
        target_section_ids = [str(sid) for sid in (target_section_ids or []) if sid]

        stages: list[tuple[str, dict[str, Any]]] = []
        if evidence_page_ids:
            stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
        if target_section_ids:
            stages.append(("target_sections", {"section_ids": target_section_ids}))
        stages.append(("case_wide", {}))

        for stage_name, extra_filters in stages:
            try:
                matches = query_ocr_chunks(
                    question,
                    case_id=case_id,
                    top_k=top_k,
                    tracker=tracker,
                    step_label=f"qc-context-{stage_name}",
                    **extra_filters,
                )
                if matches:
                    return {
                        "stage": stage_name,
                        "matches": matches,
                        "text_context": format_match_context(matches),
                    }
            except Exception as exc:
                log.warning("Pinecone query failed (stage=%s): %s", stage_name, exc)

    # Fallback: read Gemini OCR text directly from DB
    db_text = _ocr_text_from_db(case_id)
    if db_text:
        log.debug("Using DB ocr_text fallback (%d chars)", len(db_text))
        return {
            "stage": "db_ocr_text",
            "matches": [],
            "text_context": db_text,
        }

    return {"stage": "no_matches", "matches": [], "text_context": ""}


def query_case_rag(
    question: str,
    *,
    case_id: str,
    page_ids: list[str] | None = None,
    section_ids: list[str] | None = None,
    document_type_ids: list[str] | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> list[dict[str, Any]]:
    return query_ocr_chunks(
        question,
        case_id=case_id,
        page_ids=page_ids,
        section_ids=section_ids,
        document_type_ids=document_type_ids,
        top_k=top_k,
        tracker=tracker,
    )


def query_checklist_rag(
    question: str,
    *,
    case_id: str | None = None,
    checklist_id: str | None = None,
    top_k: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> list[dict[str, Any]]:
    return query_checklist_answers(
        question,
        case_id=case_id,
        checklist_id=checklist_id,
        top_k=top_k,
        tracker=tracker,
    )
