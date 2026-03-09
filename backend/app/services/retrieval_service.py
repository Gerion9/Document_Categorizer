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


def format_match_context(matches: list[dict[str, Any]], *, max_chars: int | None = None) -> str:
    if max_chars is None:
        max_chars = get_rag_settings().evidence_context_max_chars
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


def _build_retrieval_stages(
    *,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    stages: list[tuple[str, dict[str, Any]]] = []
    if evidence_page_ids:
        stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
    if target_section_ids:
        stages.append(("target_sections", {"section_ids": target_section_ids}))
    stages.append(("case_wide", {}))
    return stages


def _rank_matches(matches: list[dict[str, Any]], *, top_k: int) -> list[dict[str, Any]]:
    deduped = _dedup_matches(matches)
    ranked = sorted(deduped, key=_evidence_rank_score, reverse=True)
    return ranked[:max(1, top_k)]


def _source_pages_from_matches(matches: list[dict[str, Any]], *, max_items: int = 12) -> list[dict[str, Any]]:
    source_pages: list[dict[str, Any]] = []
    seen_page_ids: set[str] = set()
    for match in matches:
        metadata = match.get("metadata", {}) or {}
        page_id = str(metadata.get("page_id", "") or "").strip()
        if not page_id or page_id in seen_page_ids:
            continue
        seen_page_ids.add(page_id)

        page_number_raw = metadata.get("page_number")
        page_number: int | None = None
        try:
            if page_number_raw is not None:
                parsed = int(page_number_raw)
                page_number = parsed if parsed > 0 else None
        except (TypeError, ValueError):
            page_number = None

        source_pages.append(
            {
                "page_id": page_id,
                "page_number": page_number,
                "original_filename": str(metadata.get("original_filename", "") or ""),
            }
        )
        if len(source_pages) >= max_items:
            break
    return source_pages


def _query_best_stage_matches(
    question: str,
    *,
    case_id: str,
    top_k: int,
    step_prefix: str = "evidence-query",
    query_vector: list[float] | None = None,
    context_max_chars: int | None = None,
    tracker: GeminiTokenTracker | None = None,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    stages = _build_retrieval_stages(
        evidence_page_ids=evidence_page_ids,
        target_section_ids=target_section_ids,
    )
    for stage_name, extra_filters in stages:
        try:
            matches = query_ocr_chunks(
                question,
                case_id=case_id,
                top_k=top_k,
                query_vector=query_vector,
                tracker=tracker,
                step_label=f"{step_prefix}-{stage_name}",
                **extra_filters,
            )
            ranked_matches = _rank_matches(matches, top_k=top_k)
            if ranked_matches and format_match_context(ranked_matches, max_chars=context_max_chars):
                return stage_name, ranked_matches
        except Exception as exc:
            log.warning("Evidence query failed (stage=%s): %s", stage_name, exc)
    return None, []


def _ocr_text_from_db(case_id: str, *, max_chars: int | None = None) -> str:
    """Fallback: gather Gemini OCR text directly from the DB when Pinecone is not available."""
    if max_chars is None:
        max_chars = get_rag_settings().db_fallback_max_chars
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
        source_pages: list[dict[str, Any]] = []
        seen_page_ids: set[str] = set()
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
            if pg.id not in seen_page_ids:
                seen_page_ids.add(pg.id)
                source_pages.append(
                    {
                        "page_id": str(pg.id),
                        "page_number": int(pg.original_page_number or 0),
                        "original_filename": str(pg.original_filename or ""),
                    }
                )
            remaining -= len(block) + 2
            if remaining <= 0:
                break
        return "\n\n".join(blocks), source_pages
    finally:
        db.close()


def collect_evidence_bundle_for_question(
    question_text: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    top_k: int | None = None,
    query_vector: list[float] | None = None,
    max_context_chars: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    """
    Collect, rank, dedup, and format evidence for a single QC question.
    Preserves narrow-to-broad stage precedence while keeping broad fallbacks.
    Returns a structured evidence bundle compatible with Autopilot callers.
    """
    settings = get_rag_settings()
    resolved_top_k = max(1, top_k or settings.retrieval_top_k)

    if is_pinecone_configured():
        evidence_page_ids = [str(pid) for pid in (evidence_page_ids or []) if pid]
        target_section_ids = [str(sid) for sid in (target_section_ids or []) if sid]
        stage_name, ranked_matches = _query_best_stage_matches(
            question_text,
            case_id=case_id,
            top_k=resolved_top_k,
            query_vector=query_vector,
            context_max_chars=max_context_chars,
            tracker=tracker,
            step_prefix="evidence-query",
            evidence_page_ids=evidence_page_ids,
            target_section_ids=target_section_ids,
        )
        if ranked_matches:
            text_context = format_match_context(ranked_matches, max_chars=max_context_chars)
            log.debug(
                "Using %s stage for evidence collection (%d matches)",
                stage_name or "unknown",
                len(ranked_matches),
            )
            return {
                "text_context": text_context,
                "source_pages": _source_pages_from_matches(ranked_matches),
                "stage": stage_name or "unknown",
                "matches": ranked_matches,
            }

    db_text, db_source_pages = _ocr_text_from_db(case_id, max_chars=max_context_chars)
    return {
        "text_context": db_text,
        "source_pages": db_source_pages,
        "stage": "db_ocr_text" if db_text else "no_matches",
        "matches": [],
    }


def collect_evidence_for_question(
    question_text: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    top_k: int | None = None,
) -> str:
    """
    Collect, rank, dedup, and format evidence for a single QC question.
    Merges results from all retrieval stages (like OCRDocPinecone collectEvidence).
    Returns formatted text evidence string.
    """
    bundle = collect_evidence_bundle_for_question(
        question_text,
        case_id=case_id,
        evidence_page_ids=evidence_page_ids,
        target_section_ids=target_section_ids,
        top_k=top_k,
    )
    return str(bundle.get("text_context", "") or "")


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
        settings = get_rag_settings()
        resolved_top_k = max(1, top_k or settings.retrieval_top_k)
        stage_name, ranked_matches = _query_best_stage_matches(
            question,
            case_id=case_id,
            top_k=resolved_top_k,
            tracker=tracker,
            step_prefix="qc-context",
            evidence_page_ids=evidence_page_ids,
            target_section_ids=target_section_ids,
        )
        if ranked_matches:
            return {
                "stage": stage_name or "unknown",
                "matches": ranked_matches,
                "text_context": format_match_context(ranked_matches),
            }

    # Fallback: read Gemini OCR text directly from DB
    db_text, _ = _ocr_text_from_db(case_id)
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
