from __future__ import annotations

from typing import Any

from .checklist_index_service import query_checklist_answers
from .ocr_index_service import query_ocr_chunks


def format_match_context(matches: list[dict[str, Any]], *, max_chars: int = 4000) -> str:
    blocks: list[str] = []
    remaining = max_chars

    for idx, match in enumerate(matches, start=1):
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


def retrieve_qc_text_context(
    question: str,
    *,
    case_id: str,
    evidence_page_ids: list[str] | None = None,
    target_section_ids: list[str] | None = None,
    top_k: int | None = None,
) -> dict[str, Any]:
    evidence_page_ids = [str(page_id) for page_id in (evidence_page_ids or []) if page_id]
    target_section_ids = [str(section_id) for section_id in (target_section_ids or []) if section_id]

    stages: list[tuple[str, dict[str, Any]]] = []
    if evidence_page_ids:
        stages.append(("evidence_pages", {"page_ids": evidence_page_ids}))
    if target_section_ids:
        stages.append(("target_sections", {"section_ids": target_section_ids}))
    stages.append(("case_wide", {}))

    for stage_name, extra_filters in stages:
        matches = query_ocr_chunks(
            question,
            case_id=case_id,
            top_k=top_k,
            **extra_filters,
        )
        if matches:
            return {
                "stage": stage_name,
                "matches": matches,
                "text_context": format_match_context(matches),
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
) -> list[dict[str, Any]]:
    return query_ocr_chunks(
        question,
        case_id=case_id,
        page_ids=page_ids,
        section_ids=section_ids,
        document_type_ids=document_type_ids,
        top_k=top_k,
    )


def query_checklist_rag(
    question: str,
    *,
    case_id: str | None = None,
    checklist_id: str | None = None,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    return query_checklist_answers(
        question,
        case_id=case_id,
        checklist_id=checklist_id,
        top_k=top_k,
    )
