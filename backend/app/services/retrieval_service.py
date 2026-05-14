from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
import re
from typing import Any, Literal

from .checklist_index_service import query_checklist_answers
from .embedding_service import get_embedding
from .gemini_runtime_service import GeminiTokenTracker
from .ocr_index_service import query_ocr_chunks
from .pinecone_client import is_pinecone_configured
from .rag_config import get_rag_settings

log = logging.getLogger("qc_autopilot")

RetrievalProfile = Literal["generic", "qc_checklist"]

# ---------------------------------------------------------------------------
# Evidence ranking (ported from OCRDocPinecone checklistFiller.service.js)
# ---------------------------------------------------------------------------
_SELECTION_CUE_RE = re.compile(
    r"[\u2611\u2612]|\[x\]|\(x\)|\bchecked\b|\bselected\b|\bmarcado\b",
    re.IGNORECASE,
)
_YES_NO_RE = re.compile(r"\bYes\s+No\b", re.IGNORECASE)
_FORM_REFERENCE_RE = re.compile(
    r"\b(part|item|form|i\s*-\s*914a?|i\s*-\s*765|i\s*-\s*192)\b",
    re.IGNORECASE,
)
_EXTERNAL_SOURCE_HINT_RE = re.compile(
    r"\b(fbi|foia|lea|law enforcement|declaration|affidavit|criminal history|court|biocall|bio\s*call|intake)\b",
    re.IGNORECASE,
)
_FORM_QA_ECHO_RE = re.compile(
    r"(pregunta|question)\s*:\s*part\s+\d+\s+item",
    re.IGNORECASE,
)
_CHECKBOX_ANSWER_RE = re.compile(
    r"\[\s*[x ]\s*\]\s*yes|\[\s*[x ]\s*\]\s*no",
    re.IGNORECASE,
)

_SOURCE_HIERARCHY_BONUS: list[tuple[re.Pattern[str], float]] = [
    (re.compile(r"\bfbi\b|\bfederal bureau of investigation\b|\bcriminal history\b|\brap sheet\b", re.IGNORECASE), 0.30),
    (re.compile(r"\bfoia\b", re.IGNORECASE), 0.25),
    (re.compile(r"\blea\b|\blaw enforcement\b", re.IGNORECASE), 0.25),
    (re.compile(r"\bcourt\b", re.IGNORECASE), 0.20),
    (re.compile(r"\bcriminal\b", re.IGNORECASE), 0.20),
    (re.compile(r"\bdeclaration\b|\bin support of\b", re.IGNORECASE), 0.15),
    (re.compile(r"\baffidavit\b", re.IGNORECASE), 0.15),
    (re.compile(r"\bbiocall\b|\bbio\s*call\b", re.IGNORECASE), 0.05),
    (re.compile(r"\bintake\b", re.IGNORECASE), 0.05),
]


def _source_hierarchy_bonus(
    metadata: dict[str, Any],
    *,
    retrieval_profile: RetrievalProfile = "generic",
) -> float:
    """Return the highest applicable source-hierarchy bonus for a match."""
    haystack = " ".join(
        str(metadata.get(k, "") or "")
        for k in ("section_name", "document_type_code", "source_type", "original_filename")
    )
    text = str(metadata.get("text", "") or "")
    if retrieval_profile == "qc_checklist" and text:
        haystack = f"{haystack} {text[:1200]}"
    if not haystack.strip():
        return 0.0
    best = 0.0
    for pattern, bonus in _SOURCE_HIERARCHY_BONUS:
        if pattern.search(haystack):
            best = max(best, bonus)
    return best


def _form_echo_penalty(
    match: dict[str, Any],
    *,
    where_to_verify: str = "",
    retrieval_profile: RetrievalProfile = "generic",
) -> float:
    """Demote draft-form checkbox OCR when the question asks for outside records."""
    if retrieval_profile != "qc_checklist":
        return 0.0
    if not where_to_verify.strip():
        return 0.0
    if _FORM_REFERENCE_RE.search(where_to_verify):
        return 0.0
    if not _EXTERNAL_SOURCE_HINT_RE.search(where_to_verify):
        return 0.0

    metadata = match.get("metadata", {}) or {}
    text = str(metadata.get("text", "") or "")
    if not text:
        return 0.0
    if not _FORM_QA_ECHO_RE.search(text):
        return 0.0
    if not _CHECKBOX_ANSWER_RE.search(text):
        return 0.0
    return 0.40


def _evidence_rank_score(
    match: dict[str, Any],
    *,
    where_to_verify: str = "",
    retrieval_profile: RetrievalProfile = "generic",
) -> float:
    score = float(match.get("score", 0))
    metadata = match.get("metadata", {}) or {}
    text = str(metadata.get("text", ""))
    source_type = str(metadata.get("source_type", ""))

    if _SELECTION_CUE_RE.search(text):
        score += 0.15
    if _YES_NO_RE.search(text):
        score += 0.05
    if source_type.startswith("gemini"):
        score += 0.08
    score += _source_hierarchy_bonus(metadata, retrieval_profile=retrieval_profile)
    score -= _form_echo_penalty(
        match,
        where_to_verify=where_to_verify,
        retrieval_profile=retrieval_profile,
    )
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


def format_match_as_evidence(
    matches: list[dict[str, Any]],
    *,
    max_chars: int | None = None,
    where_to_verify: str = "",
    preserve_order: bool = False,
    retrieval_profile: RetrievalProfile = "generic",
) -> list[dict[str, Any]]:
    """Return ranked evidence as structured objects preserving metadata."""
    if max_chars is None:
        max_chars = get_rag_settings().evidence_context_max_chars
    ranked = (
        list(matches)
        if preserve_order
        else sorted(
            matches,
            key=lambda match: _evidence_rank_score(
                match,
                where_to_verify=where_to_verify,
                retrieval_profile=retrieval_profile,
            ),
            reverse=True,
        )
    )
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
            "sectionName": str(metadata.get("section_name", "") or ""),
            "documentType": str(metadata.get("document_type_code", "") or ""),
            "originalFilename": str(metadata.get("original_filename", "") or ""),
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


def format_match_context(
    matches: list[dict[str, Any]],
    *,
    max_chars: int | None = None,
    where_to_verify: str = "",
    preserve_order: bool = False,
    retrieval_profile: RetrievalProfile = "generic",
) -> str:
    """Format ranked evidence as a flat text string (legacy helper)."""
    evidence = format_match_as_evidence(
        matches,
        max_chars=max_chars,
        where_to_verify=where_to_verify,
        preserve_order=preserve_order,
        retrieval_profile=retrieval_profile,
    )
    blocks: list[str] = []
    for item in evidence:
        parts: list[str] = []
        page = item.get("pageNumber")
        if page:
            parts.append(f"p.{page}")
        section = item.get("sectionName", "")
        if section:
            parts.append(section)
        doc_type = item.get("documentType", "")
        if doc_type:
            parts.append(doc_type)
        label = " | ".join(parts) if parts else "unknown"
        blocks.append(f"[{label}] {item['text']}")
    return "\n\n".join(blocks)


def _build_retrieval_stages(
    *,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    preferred_source_document_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
    document_fallback_enabled: bool = True,
) -> list[tuple[str, dict[str, Any]]]:
    stages: list[tuple[str, dict[str, Any]]] = []
    if evidence_page_ids:
        stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
    if target_section_ids:
        stages.append(("target_sections", {"section_ids": target_section_ids}))
    if preferred_source_document_ids:
        stages.append(("preferred_source_document", {"source_document_ids": preferred_source_document_ids}))
    if source_document_ids:
        preferred_scope = {str(source_document_id) for source_document_id in preferred_source_document_ids or [] if source_document_id}
        full_scope = {str(source_document_id) for source_document_id in source_document_ids if source_document_id}
        if full_scope and full_scope != preferred_scope:
            stages.append(("source_document", {"source_document_ids": source_document_ids}))
    if document_fallback_enabled:
        stages.append(("case_wide", {}))
    elif not stages:
        stages.append(("case_wide", {}))
    return stages


_MAX_CHUNKS_PER_PAGE = 3
_MAX_QUERY_CANDIDATES = 60


def _candidate_query_k(
    top_k: int,
    *,
    retrieval_profile: RetrievalProfile = "generic",
) -> int:
    if retrieval_profile != "qc_checklist":
        return max(1, top_k)
    return min(_MAX_QUERY_CANDIDATES, max(top_k, (top_k * 4), top_k + 8))


def _rank_matches(
    matches: list[dict[str, Any]],
    *,
    top_k: int,
    where_to_verify: str = "",
    retrieval_profile: RetrievalProfile = "generic",
) -> list[dict[str, Any]]:
    deduped = _dedup_matches(matches)
    ranked = sorted(
        deduped,
        key=lambda match: _evidence_rank_score(
            match,
            where_to_verify=where_to_verify,
            retrieval_profile=retrieval_profile,
        ),
        reverse=True,
    )
    limit = max(1, top_k)
    result: list[dict[str, Any]] = []
    page_counts: dict[str, int] = {}
    deferred: list[dict[str, Any]] = []
    for match in ranked:
        page_id = str((match.get("metadata") or {}).get("page_id", "") or "")
        count = page_counts.get(page_id, 0)
        if count < _MAX_CHUNKS_PER_PAGE:
            page_counts[page_id] = count + 1
            result.append(match)
            if len(result) >= limit:
                break
        else:
            deferred.append(match)
    if len(result) < limit:
        for match in deferred:
            result.append(match)
            if len(result) >= limit:
                break
    return result


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
    where_to_verify: str = "",
    top_k: int,
    retrieval_profile: RetrievalProfile = "generic",
    step_prefix: str = "evidence-query",
    query_vector: list[float] | None = None,
    context_max_chars: int | None = None,
    tracker: GeminiTokenTracker | None = None,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    preferred_source_document_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
    document_fallback_enabled: bool = True,
) -> tuple[str | None, list[dict[str, Any]]]:
    stages = _build_retrieval_stages(
        evidence_page_ids=evidence_page_ids,
        target_section_ids=target_section_ids,
        preferred_source_document_ids=preferred_source_document_ids,
        source_document_ids=source_document_ids,
        document_fallback_enabled=document_fallback_enabled,
    )
    candidate_top_k = _candidate_query_k(
        max(1, top_k),
        retrieval_profile=retrieval_profile,
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
            top_k=candidate_top_k,
            query_vector=resolved_query_vector,
            # query_vector is precomputed once to avoid repeated embeddings and tracker races.
            tracker=None,
            step_label=f"{step_prefix}-{stage_name}",
            **extra_filters,
        )
        ranked_matches = _rank_matches(
            matches,
            top_k=top_k,
            where_to_verify=where_to_verify,
            retrieval_profile=retrieval_profile,
        )
        if ranked_matches and format_match_context(
            ranked_matches,
            max_chars=context_max_chars,
            where_to_verify=where_to_verify,
            preserve_order=True,
            retrieval_profile=retrieval_profile,
        ):
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

    all_stage_matches: list[dict[str, Any]] = []
    best_stage: str | None = None
    for stage_name, _ in stages:
        stage_matches = stage_results.get(stage_name) or []
        if stage_matches:
            if best_stage is None:
                best_stage = stage_name
            all_stage_matches.extend(stage_matches)

    if all_stage_matches:
        merged = _rank_matches(
            all_stage_matches,
            top_k=top_k,
            where_to_verify=where_to_verify,
            retrieval_profile=retrieval_profile,
        )
        return best_stage, merged
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
            .order_by(Page.original_page_number.asc())
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
    retrieval_profile: RetrievalProfile = "generic",
) -> list[dict[str, Any]]:
    """Secondary query filtered to OCR source types, like v1's ocrPriorityMatches."""
    try:
        matches = query_ocr_chunks(
            question,
            case_id=case_id,
            top_k=_candidate_query_k(max(1, top_k), retrieval_profile=retrieval_profile),
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
    where_to_verify: str = "",
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    preferred_source_document_ids: list[str] | None = None,
    source_document_ids: list[str] | None = None,
    top_k: int | None = None,
    query_vector: list[float] | None = None,
    max_context_chars: int | None = None,
    tracker: GeminiTokenTracker | None = None,
    document_fallback_enabled: bool | None = None,
    retrieval_profile: RetrievalProfile = "generic",
) -> dict[str, Any]:
    """
    Collect, rank, dedup, and format evidence for a single QC question.
    Uses a dual-query strategy like v1: primary retrieval + OCR-priority retrieval,
    then merge, dedup, and rank all results together.
    When source_document_ids is provided, retrieval is scoped to those documents
    with configurable fallback to case-wide search.
    When where_to_verify is provided and no pre-computed query_vector exists,
    the embedding query is enriched with the verification-source hints so that
    Pinecone returns chunks from supporting documents (declarations, reports, etc.).
    """
    settings = get_rag_settings()
    resolved_top_k = max(1, top_k or settings.retrieval_top_k)
    resolved_document_fallback = (
        settings.retrieval_document_fallback_enabled
        if document_fallback_enabled is None
        else bool(document_fallback_enabled)
    )

    if is_pinecone_configured():
        evidence_page_ids = [str(pid) for pid in (evidence_page_ids or []) if pid]
        target_section_ids = [str(sid) for sid in (target_section_ids or []) if sid]
        normalized_preferred_source_document_ids = [
            str(sd) for sd in (preferred_source_document_ids or []) if sd
        ]
        if source_document_ids is None:
            normalized_source_document_ids: list[str] | None = None
        else:
            normalized_source_document_ids = [str(sd) for sd in source_document_ids if sd]

        resolved_query_vector = query_vector
        if resolved_query_vector is None:
            wtv = (where_to_verify or "").strip()
            search_query = f"{question_text} {wtv}".strip() if wtv else question_text
            try:
                resolved_query_vector = get_embedding(
                    search_query,
                    task_type=settings.embedding_task_type_query,
                    tracker=tracker,
                    step_label="evidence-query-embedding",
                )
            except Exception as exc:
                log.warning("Evidence embedding generation failed: %s", exc)

        force_doc_scope = bool(normalized_source_document_ids) and not resolved_document_fallback
        use_doc_scope = force_doc_scope or bool(
            normalized_source_document_ids and settings.retrieval_prefer_scoped_document
        )

        stage_name, primary_matches = _query_best_stage_matches(
            question_text,
            case_id=case_id,
            where_to_verify=where_to_verify,
            top_k=resolved_top_k,
            retrieval_profile=retrieval_profile,
            query_vector=resolved_query_vector,
            context_max_chars=max_context_chars,
            tracker=None,
            step_prefix="evidence-query",
            evidence_page_ids=evidence_page_ids,
            target_section_ids=target_section_ids,
            preferred_source_document_ids=normalized_preferred_source_document_ids,
            source_document_ids=normalized_source_document_ids if use_doc_scope else None,
            document_fallback_enabled=resolved_document_fallback,
        )

        ocr_priority_matches = _query_ocr_priority_matches(
            question_text,
            case_id=case_id,
            top_k=max(4, resolved_top_k // 2),
            query_vector=resolved_query_vector,
            source_document_ids=normalized_source_document_ids if use_doc_scope else None,
            retrieval_profile=retrieval_profile,
        )

        all_matches = list(primary_matches) + list(ocr_priority_matches)
        ranked_matches = (
            _rank_matches(
                all_matches,
                top_k=resolved_top_k,
                where_to_verify=where_to_verify,
                retrieval_profile=retrieval_profile,
            )
            if all_matches
            else []
        )

        if ranked_matches:
            structured_evidence = format_match_as_evidence(
                ranked_matches,
                max_chars=max_context_chars,
                where_to_verify=where_to_verify,
                preserve_order=True,
                retrieval_profile=retrieval_profile,
            )
            text_context = format_match_context(
                ranked_matches,
                max_chars=max_context_chars,
                where_to_verify=where_to_verify,
                preserve_order=True,
                retrieval_profile=retrieval_profile,
            )
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
