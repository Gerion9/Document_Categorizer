"""Reusable helpers extracted from the QC checklist router."""

from __future__ import annotations

from pathlib import Path
import re

from sqlalchemy.orm import Session

from ..models import DocumentType, Page, PageSectionLink, QCChecklist, QCPart, QCQuestion, Section

_LOOKUP_TOKEN_VARIANTS: dict[str, set[str]] = {
    "application": {"applications", "app"},
    "applications": {"application", "app"},
    "app": {"application", "applications"},
    "certificate": {"cert"},
    "cert": {"certificate"},
    "document": {"documents", "docs", "doc"},
    "documents": {"document", "docs", "doc"},
    "docs": {"document", "documents", "doc"},
    "doc": {"document", "documents", "docs"},
    "record": {"records"},
    "records": {"record"},
}
_FORM_I914A_RE = re.compile(r"\bi\s*914a\b|\bsupplement\s*a\b", re.IGNORECASE)
_FORM_I914_RE = re.compile(r"\bi\s*914\b", re.IGNORECASE)
_FORM_I765_RE = re.compile(r"\bi\s*765\b", re.IGNORECASE)
_FORM_I192_RE = re.compile(r"\bi\s*192\b", re.IGNORECASE)
_SOURCE_DOCUMENT_ALIAS_VARIANTS: dict[str, set[str]] = {
    "bc": {"birth certificate", "birth cert"},
    "birth cert": {"birth certificate", "bc"},
    "birth certificate": {"birth cert", "bc"},
    "bio call": {"biocall"},
    "biocall": {"bio call"},
    "declaration": {"affidavit", "in support of"},
    "affidavit": {"declaration"},
    "fbi": {"fbi record", "fbi records", "criminal history", "criminal history record", "rap sheet"},
    "fbi record": {"fbi", "criminal history", "criminal history record"},
    "fbi records": {"fbi", "criminal history", "criminal history record"},
    "criminal history": {"fbi", "criminal history record", "rap sheet"},
    "criminal history record": {"fbi", "criminal history", "rap sheet"},
    "rap sheet": {"fbi", "criminal history", "criminal history record"},
    "ident letter": {"identity letter", "identification letter"},
    "identity letter": {"ident letter", "identification letter"},
    "identification letter": {"ident letter", "identity letter"},
    "lea": {"law enforcement", "law enforcement agency"},
    "law enforcement": {"lea", "law enforcement agency"},
    "law enforcement agency": {"lea", "law enforcement"},
}


def normalize_lookup_text(value: str) -> str:
    normalized = str(value or "").lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def expand_lookup_aliases(value: str) -> set[str]:
    normalized = normalize_lookup_text(value)
    if not normalized:
        return set[str]()

    variants = {normalized}
    if normalized.startswith("form "):
        variants.add(normalized.removeprefix("form ").strip())

    without_prefix = re.sub(r"^(original)\s+", "", normalized).strip()
    without_suffix = re.sub(r"\s+(draft|drafts)$", "", normalized).strip()
    for candidate in (without_prefix, without_suffix):
        if candidate and candidate != normalized:
            variants.add(candidate)

    tokens = normalized.split()
    for idx, token in enumerate(tokens):
        for replacement in _LOOKUP_TOKEN_VARIANTS.get(token, set()):
            alias_tokens = tokens.copy()
            alias_tokens[idx] = replacement
            variants.add(" ".join(alias_tokens).strip())

    return {variant for variant in variants if len(variant) >= 2}


def split_lookup_parts(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;/(),]+", str(value or "")) if part.strip()]


def _expand_source_document_aliases(value: str) -> set[str]:
    normalized = normalize_lookup_text(value)
    if not normalized:
        return set[str]()

    variants = {normalized}
    tokens = normalized.split()
    for idx, token in enumerate(tokens):
        if len(token) >= 2:
            variants.add(token)
        if idx + 1 < len(tokens):
            variants.add(" ".join(tokens[idx : idx + 2]))
        if idx + 2 < len(tokens):
            variants.add(" ".join(tokens[idx : idx + 3]))

    expanded = set(variants)
    for variant in list(variants):
        expanded.update(_SOURCE_DOCUMENT_ALIAS_VARIANTS.get(variant, set()))

    return {variant for variant in expanded if len(variant) >= 2}


def build_case_source_document_alias_index(
    case_id: str,
    db: Session,
    *,
    source_document_ids: list[str] | None = None,
) -> dict[str, set[str]]:
    page_query = (
        db.query(Page.source_document_id, Page.original_filename, DocumentType.name)
        .outerjoin(DocumentType, DocumentType.id == Page.document_type_id)
        .filter(
            Page.case_id == case_id,
            Page.deleted_at.is_(None),
            Page.source_document_id.isnot(None),
        )
    )
    if source_document_ids is not None:
        if not source_document_ids:
            return {}
        page_query = page_query.filter(Page.source_document_id.in_(source_document_ids))

    rows = page_query.all()
    grouped_candidates: dict[str, set[str]] = {}
    for source_document_id, original_filename, document_type_name in rows:
        source_document_id = str(source_document_id or "").strip()
        if not source_document_id:
            continue

        candidates = grouped_candidates.setdefault(source_document_id, set())
        filename = str(original_filename or "").strip()
        if filename:
            stem = Path(filename).stem
            candidates.add(filename)
            candidates.add(stem)
            candidates.update(
                part.strip()
                for part in re.split(r"[_\-.]+", stem)
                if len(part.strip()) >= 2
            )
        if document_type_name:
            candidates.add(str(document_type_name))

    alias_index: dict[str, set[str]] = {}
    for source_document_id, candidates in grouped_candidates.items():
        aliases: set[str] = set()
        for candidate in candidates:
            aliases.update(_expand_source_document_aliases(candidate))
        for alias in aliases:
            alias_index.setdefault(alias, set()).add(source_document_id)

    return alias_index


def resolve_source_document_targets(
    where_to_verify: str,
    alias_index: dict[str, set[str]],
) -> list[str]:
    normalized_text = normalize_lookup_text(where_to_verify)
    if not normalized_text:
        return []

    matches: list[tuple[int, int, int, str]] = []
    for alias, source_document_ids in alias_index.items():
        if not alias:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        for match in re.finditer(pattern, normalized_text):
            for source_document_id in sorted(source_document_ids):
                matches.append((len(alias), match.start(), match.end(), source_document_id))

    matches.sort(key=lambda item: (item[1], -(item[0]), item[3]))
    occupied_spans: list[tuple[int, int]] = []
    resolved_source_document_ids: list[str] = []

    for _, start, end, source_document_id in matches:
        span = (start, end)
        if any(spans_overlap(span, occupied) for occupied in occupied_spans):
            continue
        occupied_spans.append(span)
        if source_document_id not in resolved_source_document_ids:
            resolved_source_document_ids.append(source_document_id)

    return resolved_source_document_ids


def build_case_section_alias_index(case_id: str, db: Session) -> dict[str, set[str]]:
    sections = (
        db.query(Section)
        .filter(Section.document_type.has(case_id=case_id))
        .order_by(Section.path_code.asc(), Section.name.asc())
        .all()
    )
    sections_per_doc_type: dict[str, int] = {}
    for section in sections:
        sections_per_doc_type[section.document_type_id] = sections_per_doc_type.get(section.document_type_id, 0) + 1

    alias_index: dict[str, set[str]] = {}
    for section in sections:
        doc_type = section.document_type
        raw_candidates = {section.name or "", section.path_code or ""}
        for part in split_lookup_parts(section.name or ""):
            raw_candidates.add(part)
        if doc_type:
            raw_candidates.add(f"{doc_type.name} {section.name}".strip())
            if sections_per_doc_type.get(section.document_type_id, 0) == 1:
                raw_candidates.add(doc_type.name or "")

        aliases: set[str] = set()
        for candidate in raw_candidates:
            aliases.update(expand_lookup_aliases(candidate))

        for alias in aliases:
            alias_index.setdefault(alias, set()).add(section.id)

    return alias_index


def spans_overlap(span_a: tuple[int, int], span_b: tuple[int, int]) -> bool:
    return not (span_a[1] <= span_b[0] or span_a[0] >= span_b[1])


def resolve_auto_link_targets(
    where_to_verify: str,
    alias_index: dict[str, set[str]],
) -> list[str]:
    normalized_text = normalize_lookup_text(where_to_verify)
    if not normalized_text:
        return []

    matches: list[tuple[int, int, int, str]] = []
    for alias, section_ids in alias_index.items():
        if len(section_ids) != 1 or not alias:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
        for match in re.finditer(pattern, normalized_text):
            matches.append((len(alias), match.start(), match.end(), next(iter(section_ids))))

    matches.sort(key=lambda item: (item[0], item[2] - item[1]), reverse=True)
    occupied_spans: list[tuple[int, int]] = []
    resolved_section_ids: list[str] = []

    for _, start, end, section_id in matches:
        span = (start, end)
        if any(spans_overlap(span, occupied) for occupied in occupied_spans):
            continue
        occupied_spans.append(span)
        if section_id not in resolved_section_ids:
            resolved_section_ids.append(section_id)

    return resolved_section_ids


def part_sort_key(part: QCPart) -> tuple[int, str]:
    return (part.order or 0, part.code or "")


def question_sort_key(question: QCQuestion) -> tuple[int, str]:
    return (question.order or 0, question.code or "")


def ordered_questions_for_checklist(cl: QCChecklist) -> list[QCQuestion]:
    all_parts = list(cl.parts)
    by_id = {p.id: p for p in all_parts}
    by_parent: dict[str | None, list[QCPart]] = {}
    for part in all_parts:
        by_parent.setdefault(part.parent_part_id, []).append(part)

    for children in by_parent.values():
        children.sort(key=part_sort_key)

    ordered_questions: list[QCQuestion] = []
    visited_parts: set[str] = set()

    def walk(part_id: str) -> None:
        part = by_id.get(part_id)
        if not part or part.id in visited_parts:
            return
        visited_parts.add(part.id)
        ordered_questions.extend(sorted(part.questions, key=question_sort_key))
        for child in by_parent.get(part.id, []):
            walk(child.id)

    for root in by_parent.get(None, []):
        walk(root.id)

    for orphan in sorted(all_parts, key=part_sort_key):
        if orphan.id not in visited_parts:
            walk(orphan.id)

    return ordered_questions


def ordered_questions_for_part(part: QCPart, all_parts: list[QCPart]) -> list[QCQuestion]:
    by_id = {p.id: p for p in all_parts}
    by_parent: dict[str | None, list[QCPart]] = {}
    for node in all_parts:
        by_parent.setdefault(node.parent_part_id, []).append(node)

    for children in by_parent.values():
        children.sort(key=part_sort_key)

    ordered_questions: list[QCQuestion] = []
    visited_parts: set[str] = set()

    def walk(part_id: str) -> None:
        node = by_id.get(part_id)
        if not node or node.id in visited_parts:
            return
        visited_parts.add(node.id)
        ordered_questions.extend(sorted(node.questions, key=question_sort_key))
        for child in by_parent.get(node.id, []):
            walk(child.id)

    walk(part.id)
    return ordered_questions


def auto_link_checklist_questions(cl: QCChecklist, db: Session) -> tuple[int, int]:
    if not cl.case_id:
        return 0, 0

    alias_index = build_case_section_alias_index(cl.case_id, db)
    if not alias_index:
        return 0, 0

    linked_questions = 0
    resolved_sections = 0
    for question in ordered_questions_for_checklist(cl):
        if question.target_section_ids or not (question.where_to_verify or "").strip():
            continue
        resolved = resolve_auto_link_targets(question.where_to_verify, alias_index)
        if not resolved:
            continue
        question.target_section_ids = resolved
        linked_questions += 1
        resolved_sections += len(resolved)

    return linked_questions, resolved_sections


def infer_form_type_from_text(text: str) -> str:
    normalized_text = normalize_lookup_text(text)
    if not normalized_text:
        return ""
    if _FORM_I914A_RE.search(normalized_text):
        return "i-914a"
    if _FORM_I914_RE.search(normalized_text):
        return "i-914"
    if _FORM_I765_RE.search(normalized_text):
        return "i-765"
    if _FORM_I192_RE.search(normalized_text):
        return "i-192"
    return ""


def question_sections(q: QCQuestion, db: Session) -> list[Section]:
    sections_by_id: dict[str, Section] = {}
    for section_id in q.target_section_ids or []:
        section = db.query(Section).filter(Section.id == section_id).first()
        if section:
            sections_by_id[section.id] = section

    for evidence in q.evidence:
        page = db.query(Page).filter(Page.id == evidence.page_id, Page.deleted_at.is_(None)).first()
        if not page:
            continue
        if page.section_id:
            section = db.query(Section).filter(Section.id == page.section_id).first()
            if section:
                sections_by_id[section.id] = section
        for link in page.section_links or []:
            section = getattr(link, "section", None)
            if section:
                sections_by_id[section.id] = section

    return list(sections_by_id.values())


def infer_form_type_for_question(q: QCQuestion, db: Session) -> str:
    candidate_texts: list[str] = []
    for section in question_sections(q, db):
        candidate_texts.extend(
            [
                section.name or "",
                section.path_code or "",
                section.document_type.name if section.document_type else "",
            ]
        )

    candidate_texts.extend([q.where_to_verify or "", q.description or ""])

    checklist = q.part.checklist if q.part else None
    if checklist:
        candidate_texts.extend([checklist.name or "", checklist.description or ""])

    for form_type in ("i-914a", "i-914", "i-765", "i-192", "i-360", "g-28", "g-1145"):
        for candidate in candidate_texts:
            if infer_form_type_from_text(candidate) == form_type:
                return form_type
    return ""


def pages_for_target_section(
    section_id: str,
    db: Session,
    *,
    limit: int,
    source_document_ids: list[str] | None = None,
) -> list[Page]:
    if source_document_ids is not None and not source_document_ids:
        return []

    page_query = (
        db.query(Page)
        .join(PageSectionLink, PageSectionLink.page_id == Page.id)
        .filter(PageSectionLink.section_id == section_id, Page.deleted_at.is_(None))
        .order_by(PageSectionLink.is_primary.desc(), PageSectionLink.order_in_section.asc())
    )
    if source_document_ids is not None:
        page_query = page_query.filter(Page.source_document_id.in_(source_document_ids))

    linked_pages = page_query.limit(limit).all()
    if linked_pages:
        return linked_pages

    fallback_query = (
        db.query(Page)
        .filter(Page.section_id == section_id, Page.deleted_at.is_(None))
        .order_by(Page.order_in_section)
    )
    if source_document_ids is not None:
        fallback_query = fallback_query.filter(Page.source_document_id.in_(source_document_ids))
    return fallback_query.limit(limit).all()
