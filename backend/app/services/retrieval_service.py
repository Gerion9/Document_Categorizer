from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import re
from typing import Any

from .checklist_index_service import query_checklist_answers
from .embedding_service import get_embedding
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


def format_match_as_evidence(matches: list[dict[str, Any]], *, max_chars: int | None = None) -> list[dict[str, Any]]:
    """Return ranked evidence as structured objects preserving metadata."""
    if max_chars is None:
        max_chars = get_rag_settings().evidence_context_max_chars
    ranked = sorted(matches, key=_evidence_rank_score, reverse=True)
    evidence: list[dict[str, Any]] = []
    remaining = max_chars

    for match in ranked:
        metadata = match.get("metadata", {}) or {}
        text = metadata.get("text") or metadata.get("explanation") or metadata.get("question") or ""
        snippet = str(text).strip()
        if not snippet:
            continue

        page_number = metadata.get("page_number") or metadata.get("page_id")
        try:
            page_number = int(page_number) if page_number is not None else None
        except (TypeError, ValueError):
            page_number = None

        item: dict[str, Any] = {
            "score": round(float(match.get("score", 0)), 3),
            "pageNumber": page_number,
            "chunkOrder": int(metadata.get("chunk_order", 0) or 0),
            "text": snippet,
            "sourceType": str(metadata.get("source_type", "") or ""),
        }

        cost = len(snippet) + 80
        if cost > remaining:
            item["text"] = snippet[: max(0, remaining - 80)].rstrip()
            if not item["text"]:
                break
        evidence.append(item)
        remaining -= cost
        if remaining <= 0:
            break

    return evidence


def format_match_context(matches: list[dict[str, Any]], *, max_chars: int | None = None) -> str:
    """Format ranked evidence as a flat text string (legacy helper)."""
    evidence = format_match_as_evidence(matches, max_chars=max_chars)
    blocks: list[str] = []
    for item in evidence:
        page = item.get("pageNumber")
        page_label = f"p.{page}" if page else "unknown"
        blocks.append(f"[{page_label}] {item['text']}")
    return "\n\n".join(blocks)


def _build_retrieval_stages(
    *,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
    document_fallback_enabled: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    stages: list[tuple[str, dict[str, Any]]] = []
    if evidence_page_ids:
        stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
    if target_section_ids:
        stages.append(("target_sections", {"section_ids": target_section_ids}))
    if source_document_ids:
        stages.append(("source_document", {"source_document_ids": source_document_ids}))
    if document_fallback_enabled:
        stages.append(("case_wide", {}))
    elif not stages:
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
    source_document_ids: list[str] | None = None,
    document_fallback_enabled: bool = True,
) -> tuple[str | None, list[dict[str, Any]]]:
    stages = _build_retrieval_stages(
        evidence_page_ids=evidence_page_ids,
        target_section_ids=target_section_ids,
        source_document_ids=source_document_ids,
        document_fallback_enabled=document_fallback_enabled,
    )
    resolved_query_vector = query_vector
    if resolved_query_vector is None:
        try:
            settings = get_rag_settings()
            resolved_query_vector = get_embedding(
                question,
                task_type=settings.embedding_task_type_query,
                tracker=tracker,
                step_label=f"{step_prefix}-embedding",
            )
        except Exception as exc:
            log.warning("Evidence embedding generation failed: %s", exc)

    def _query_stage(stage_name: str, extra_filters: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        matches = query_ocr_chunks(
            question,
            case_id=case_id,
            top_k=top_k,
            query_vector=resolved_query_vector,
            # query_vector is precomputed once to avoid repeated embeddings and tracker races.
            tracker=None,
            step_label=f"{step_prefix}-{stage_name}",
            **extra_filters,
        )
        ranked_matches = _rank_matches(matches, top_k=top_k)
        if ranked_matches and format_match_context(ranked_matches, max_chars=context_max_chars):
            return stage_name, ranked_matches
        return stage_name, []

    stage_results: dict[str, list[dict[str, Any]]] = {}
    if len(stages) <= 1:
        for stage_name, extra_filters in stages:
            try:
                _, ranked_matches = _query_stage(stage_name, extra_filters)
                stage_results[stage_name] = ranked_matches
            except Exception as exc:
                log.warning("Evidence query failed (stage=%s): %s", stage_name, exc)
    else:
        with ThreadPoolExecutor(max_workers=len(stages)) as pool:
            future_to_stage = {
                pool.submit(_query_stage, stage_name, extra_filters): stage_name
                for stage_name, extra_filters in stages
            }
            for future in as_completed(future_to_stage):
                stage_name = future_to_stage[future]
                try:
                    _, ranked_matches = future.result()
                    stage_results[stage_name] = ranked_matches
                except Exception as exc:
                    log.warning("Evidence query failed (stage=%s): %s", stage_name, exc)

    for stage_name, _ in stages:
        ranked_matches = stage_results.get(stage_name) or []
        if ranked_matches:
            return stage_name, ranked_matches
    return None, []


def _ocr_text_from_db(case_id: str, *, max_chars: int | None = None) -> tuple[str, list[dict[str, Any]]]:
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
            block = f"--- Page {pg.original_page_number} ---\n{text}"
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


_OCR_PRIORITY_SOURCE_TYPES = ["gemini_ocr", "gemini_tables", "gemini-vision", "gemini-vision-empty"]


def _query_ocr_priority_matches(
    question: str,
    *,
    case_id: str,
    top_k: int,
    query_vector: list[float] | None = None,
    source_document_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Secondary query filtered to OCR source types, like v1's ocrPriorityMatches."""
    try:
        matches = query_ocr_chunks(
            question,
            case_id=case_id,
            top_k=max(1, top_k),
            query_vector=query_vector,
            tracker=None,
            step_label="evidence-ocr-priority",
            source_types=_OCR_PRIORITY_SOURCE_TYPES,
            source_document_ids=source_document_ids,
        )
        return matches
    except Exception as exc:
        log.warning("OCR-priority retrieval failed, continuing with primary: %s", exc)
        return []


def collect_evidence_bundle_for_question(
    question_text: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
    top_k: int | None = None,
    query_vector: list[float] | None = None,
    max_context_chars: int | None = None,
    tracker: GeminiTokenTracker | None = None,
) -> dict[str, Any]:
    """
    Collect, rank, dedup, and format evidence for a single QC question.
    Uses a dual-query strategy like v1: primary retrieval + OCR-priority retrieval,
    then merge, dedup, and rank all results together.
    When source_document_ids is provided, retrieval is scoped to those documents
    with configurable fallback to case-wide search.
    """
    settings = get_rag_settings()
    resolved_top_k = max(1, top_k or settings.retrieval_top_k)

    if is_pinecone_configured():
        evidence_page_ids = [str(pid) for pid in (evidence_page_ids or []) if pid]
        target_section_ids = [str(sid) for sid in (target_section_ids or []) if sid]
        source_document_ids = [str(sd) for sd in (source_document_ids or []) if sd] if source_document_ids else None

        resolved_query_vector = query_vector
        if resolved_query_vector is None:
            try:
                resolved_query_vector = get_embedding(
                    question_text,
                    task_type=settings.embedding_task_type_query,
                    tracker=tracker,
                    step_label="evidence-query-embedding",
                )
            except Exception as exc:
                log.warning("Evidence embedding generation failed: %s", exc)

        use_doc_scope = source_document_ids and settings.retrieval_prefer_scoped_document

        stage_name, primary_matches = _query_best_stage_matches(
            question_text,
            case_id=case_id,
            top_k=resolved_top_k,
            query_vector=resolved_query_vector,
            context_max_chars=max_context_chars,
            tracker=None,
            step_prefix="evidence-query",
            evidence_page_ids=evidence_page_ids,
            target_section_ids=target_section_ids,
            source_document_ids=source_document_ids if use_doc_scope else None,
            document_fallback_enabled=settings.retrieval_document_fallback_enabled,
        )

        ocr_priority_matches = _query_ocr_priority_matches(
            question_text,
            case_id=case_id,
            top_k=max(4, resolved_top_k // 2),
            query_vector=resolved_query_vector,
            source_document_ids=source_document_ids if use_doc_scope else None,
        )

        all_matches = list(primary_matches) + list(ocr_priority_matches)
        ranked_matches = _rank_matches(all_matches, top_k=resolved_top_k) if all_matches else []

        if ranked_matches:
            structured_evidence = format_match_as_evidence(ranked_matches, max_chars=max_context_chars)
            text_context = format_match_context(ranked_matches, max_chars=max_context_chars)
            log.debug(
                "Evidence collected: stage=%s primary=%d ocr_priority=%d merged=%d",
                stage_name or "unknown",
                len(primary_matches),
                len(ocr_priority_matches),
                len(ranked_matches),
            )
            return {
                "text_context": text_context,
                "evidence": structured_evidence,
                "source_pages": _source_pages_from_matches(ranked_matches),
                "stage": stage_name or "merged",
                "matches": ranked_matches,
            }

    db_text, db_source_pages = _ocr_text_from_db(case_id, max_chars=max_context_chars)
    return {
        "text_context": db_text,
        "evidence": [],
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
    Delegates to collect_evidence_bundle_for_question and maps the result.
    """
    bundle = collect_evidence_bundle_for_question(
        question,
        case_id=case_id,
        evidence_page_ids=evidence_page_ids,
        target_section_ids=target_section_ids,
        top_k=top_k,
        tracker=tracker,
    )
    return {
        "stage": bundle.get("stage", "no_matches"),
        "matches": bundle.get("matches", []),
        "text_context": bundle.get("text_context", ""),
    }


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
