"""Helpers for case-level source document scopes."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from sqlalchemy.orm import Session

from ..models import Case, Page
from ..utils.text import clean_text as _clean_text

DocumentScopeName = Literal["form_filling", "qc_checklist"]

CASE_DOCUMENT_SCOPE_FIELDS: dict[DocumentScopeName, str] = {
    "form_filling": "form_filling_source_document_ids",
    "qc_checklist": "qc_checklist_source_document_ids",
}


def normalize_source_document_ids(values: Sequence[str] | None) -> list[str]:
    if values is None:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def get_case_scope_source_document_ids(
    case: Case | None,
    scope_name: DocumentScopeName,
) -> list[str] | None:
    if case is None:
        return None

    field_name = CASE_DOCUMENT_SCOPE_FIELDS[scope_name]
    raw_value = getattr(case, field_name, None)
    if raw_value is None:
        return None
    if not isinstance(raw_value, Sequence) or isinstance(raw_value, (str, bytes)):
        return []
    return normalize_source_document_ids(list(raw_value))


def set_case_scope_source_document_ids(
    case: Case,
    scope_name: DocumentScopeName,
    source_document_ids: Sequence[str] | None,
) -> None:
    field_name = CASE_DOCUMENT_SCOPE_FIELDS[scope_name]
    if source_document_ids is None:
        setattr(case, field_name, None)
        return

    setattr(case, field_name, normalize_source_document_ids(source_document_ids))


def load_case_pages_for_scope(
    db: Session,
    case_id: str,
    *,
    source_document_ids: Sequence[str] | None = None,
) -> list[Page]:
    query = (
        db.query(Page)
        .filter(Page.case_id == case_id, Page.deleted_at.is_(None))
        .order_by(Page.original_page_number.asc(), Page.created_at.asc())
    )
    if source_document_ids is None:
        return query.all()

    normalized = normalize_source_document_ids(source_document_ids)
    if not normalized:
        return []
    return query.filter(Page.source_document_id.in_(normalized)).all()


def filter_page_ids_to_scope(
    db: Session,
    page_ids: Sequence[str],
    *,
    source_document_ids: Sequence[str] | None = None,
    case_id: str | None = None,
) -> list[str]:
    ordered_page_ids = normalize_source_document_ids(page_ids)
    if not ordered_page_ids or source_document_ids is None:
        return ordered_page_ids

    normalized_scope = normalize_source_document_ids(source_document_ids)
    if not normalized_scope:
        return []

    query = db.query(Page.id).filter(
        Page.id.in_(ordered_page_ids),
        Page.deleted_at.is_(None),
        Page.source_document_id.in_(normalized_scope),
    )
    if case_id:
        query = query.filter(Page.case_id == case_id)

    allowed_ids = {str(page_id) for (page_id,) in query.all()}
    return [page_id for page_id in ordered_page_ids if page_id in allowed_ids]
