"""Append editable I-914 Part 9 continuation sheets to a filled PDF.

Overflow entries beyond the four native AcroForm slots on page 12 of ``i-914.pdf``
are written onto additional copies of that same page.

Root-cause note (overlap / bled values): USCIS templates reuse the same AcroForm
field names on every page. When ``insert_pdf`` brings a fresh copy of page 12 into
the already-filled document, same-named fields are merged, so the new sheet would
otherwise inherit the native page-12 values (and overlay drawing on top produced
the visible overlap). To prevent this we rename the template's Part 9 widgets to
unique ``P9S<sheet>_`` names *before* inserting, so each continuation sheet has its
own independent, editable fields and never inherits the native values.

The flat ``i-914_part9.pdf`` supplemental template remains registered for S3 sync
and reference; generation uses the fillable page 12 from ``i-914.pdf``.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import fitz
from sqlalchemy.orm import Session

from ..models import FormTemplate
from ..utils.text import clean_text as _clean_text
from .form_registry import (
    I914_PART9_CONTINUATION_FORM_TYPE,
    get_supplemental_form_template_spec,
)
from .paths import FORMS_PREFIX
from .questionnaire_service import get_form_template_path

log = logging.getLogger(__name__)

NATIVE_PART9_SLOTS = 4
DEFAULT_ENTRIES_PER_PAGE = 4
I914_FORM_TYPE = "i-914"
I914_PART9_PAGE_INDEX = 11  # zero-based index of Part 9 (page 12)

_PART9_LINE_RE = re.compile(r"p10_line([2-5])", re.IGNORECASE)


@dataclass
class ContinuationReport:
    """Result of appending Part 9 continuation template pages."""

    entries_count: int = 0
    pages_added: int = 0
    truncated_entries: list[dict[str, str]] = field(default_factory=list)


def resolve_part9_template_bytes(db: Session | None = None) -> bytes:
    """Load the flat Part 9 reference PDF (``i-914_part9.pdf``) from disk or S3."""
    spec = get_supplemental_form_template_spec(I914_PART9_CONTINUATION_FORM_TYPE)
    local_path = spec.pdf_path()
    if local_path.exists():
        return local_path.read_bytes()

    s3_key = f"{FORMS_PREFIX}/{spec.pdf_filename}"
    if db is not None:
        row = (
            db.query(FormTemplate)
            .filter(FormTemplate.form_type == spec.form_type)
            .first()
        )
        if row and _clean_text(row.s3_key):
            s3_key = _clean_text(row.s3_key)

    try:
        from ..dependencies import get_s3_service

        s3 = get_s3_service()
        return s3.download_bytes(s3_key)
    except Exception as exc:
        raise FileNotFoundError(
            f"Part 9 continuation template not found at {local_path} or S3 key {s3_key}."
        ) from exc


def resolve_i914_main_template_bytes(db: Session | None = None) -> bytes:
    """Load the fillable I-914 main form PDF (page 12 supplies Part 9 widgets)."""
    local_path = get_form_template_path(I914_FORM_TYPE)
    if local_path.exists():
        return local_path.read_bytes()

    s3_key = f"{FORMS_PREFIX}/{local_path.name}"
    if db is not None:
        row = (
            db.query(FormTemplate)
            .filter(FormTemplate.form_type == I914_FORM_TYPE)
            .first()
        )
        if row and _clean_text(row.s3_key):
            s3_key = _clean_text(row.s3_key)

    try:
        from ..dependencies import get_s3_service

        s3 = get_s3_service()
        return s3.download_bytes(s3_key)
    except Exception as exc:
        raise FileNotFoundError(
            f"I-914 template not found at {local_path} or S3 key {s3_key}."
        ) from exc


def append_fillable_part9_pages_with_report(
    pdf_bytes: bytes,
    *,
    main_template_bytes: bytes,
    header: Mapping[str, str],
    entries: Sequence[Mapping[str, str]],
    entries_per_page: int = DEFAULT_ENTRIES_PER_PAGE,
) -> tuple[bytes | None, ContinuationReport]:
    """Append fillable Part 9 continuation page(s) cloned from I-914 page 12."""
    report = ContinuationReport(entries_count=len(entries))
    if not entries:
        return None, report

    chunk_size = max(1, int(entries_per_page or DEFAULT_ENTRIES_PER_PAGE))
    chunks = [
        list(entries[index : index + chunk_size])
        for index in range(0, len(entries), chunk_size)
    ]

    if not main_template_bytes:
        raise ValueError("I-914 main template bytes are required for Part 9 continuation.")

    current_bytes = pdf_bytes
    for sheet_number, chunk in enumerate(chunks, start=1):
        current_bytes = _append_single_fillable_part9_page(
            current_bytes,
            main_template_bytes=main_template_bytes,
            header=header,
            entries=chunk,
            sheet_number=sheet_number,
        )

    from .pdf_form_service import _force_disable_need_appearances

    target_doc = fitz.open(stream=current_bytes, filetype="pdf")
    try:
        _force_disable_need_appearances(target_doc)
        report.pages_added = len(chunks)
        return target_doc.tobytes(deflate=True), report
    finally:
        target_doc.close()


def _append_single_fillable_part9_page(
    pdf_bytes: bytes,
    *,
    main_template_bytes: bytes,
    header: Mapping[str, str],
    entries: Sequence[Mapping[str, str]],
    sheet_number: int,
) -> bytes:
    """Append exactly one fillable Part 9 continuation sheet to a PDF.

    The template's Part 9 widgets are renamed to unique ``P9S<sheet>_`` names
    *before* the page is inserted, so the new sheet keeps its own independent
    fields and never inherits the native page-12 (or other sheets') values.
    """
    target_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    main_doc = fitz.open(stream=main_template_bytes, filetype="pdf")
    if main_doc.page_count <= I914_PART9_PAGE_INDEX:
        main_doc.close()
        target_doc.close()
        raise ValueError("I-914 template does not contain Part 9 page 12.")

    try:
        _rename_template_part9_widgets(main_doc, sheet_number=sheet_number)
        target_doc.insert_pdf(
            main_doc,
            from_page=I914_PART9_PAGE_INDEX,
            to_page=I914_PART9_PAGE_INDEX,
        )
        page = target_doc[-1]
        _fill_part9_page(page, header=header, entries=entries)
        return target_doc.tobytes(deflate=True)
    finally:
        main_doc.close()
        target_doc.close()


def append_continuation_pages_with_report(
    pdf_bytes: bytes,
    *,
    header: Mapping[str, str],
    entries: Sequence[Mapping[str, str]],
    entries_per_page: int = DEFAULT_ENTRIES_PER_PAGE,
    db: Session | None = None,
) -> tuple[bytes | None, ContinuationReport]:
    """Append editable Part 9 continuation sheets; entry point for form filling."""
    main_template_bytes = resolve_i914_main_template_bytes(db)
    return append_fillable_part9_pages_with_report(
        pdf_bytes,
        main_template_bytes=main_template_bytes,
        header=header,
        entries=entries,
        entries_per_page=entries_per_page,
    )


def append_continuation_pages(
    pdf_bytes: bytes,
    *,
    header: Mapping[str, str],
    entries: Sequence[Mapping[str, str]],
    entries_per_page: int = DEFAULT_ENTRIES_PER_PAGE,
    db: Session | None = None,
) -> bytes | None:
    result_bytes, _ = append_continuation_pages_with_report(
        pdf_bytes,
        header=header,
        entries=entries,
        entries_per_page=entries_per_page,
        db=db,
    )
    return result_bytes


def _rename_template_part9_widgets(
    template_doc: fitz.Document, *, sheet_number: int
) -> None:
    """Assign unique /T names to the template page-12 Part 9 widgets.

    Done on the template before ``insert_pdf`` so same-named native fields are
    never merged with the new sheet. Detaches any shared ``/Parent`` first.
    """
    page = template_doc[I914_PART9_PAGE_INDEX]
    for widget in page.widgets():
        field_name = _clean_text(getattr(widget, "field_name", ""))
        if not field_name or "pdf417" in field_name.lower():
            continue
        if not _is_part9_continuation_widget(field_name):
            continue
        short_name = field_name.split(".")[-1].replace("[", "").replace("]", "")
        new_name = f"P9S{sheet_number}_{short_name}"
        xref = widget.xref
        try:
            parent_ref = template_doc.xref_get_key(xref, "Parent")
            if parent_ref and parent_ref[0] != "null":
                template_doc.xref_set_key(xref, "Parent", "null")
        except Exception:
            pass
        try:
            template_doc.xref_set_key(xref, "T", f"({new_name})")
        except Exception as exc:
            log.warning(
                "Could not assign unique Part 9 field name for sheet %s (%s): %s",
                sheet_number,
                field_name,
                exc,
            )


def _fill_part9_page(
    page: fitz.Page,
    *,
    header: Mapping[str, str],
    entries: Sequence[Mapping[str, str]],
) -> None:
    """Fill a Part 9 page's AcroForm widgets (header + entry slots) by value."""
    family = _coerce_str(header.get("family_name"))
    given = _coerce_str(header.get("given_name"))
    middle = _coerce_str(header.get("middle_name"))
    a_number = _format_a_number(header.get("a_number"))

    slot_values: list[dict[str, str]] = [
        {
            "page_number": _coerce_str(entry.get("page_number")),
            "part_number": _coerce_str(entry.get("part_number")),
            "item_number": _coerce_str(entry.get("item_number")),
            "additional_information": _coerce_str(entry.get("additional_information")),
        }
        for entry in entries
    ]

    for widget in page.widgets():
        field_name = _clean_text(getattr(widget, "field_name", ""))
        if not field_name:
            continue

        header_key = _classify_part9_header_field(field_name)
        if header_key is not None:
            value = {
                "family_name": family,
                "given_name": given,
                "middle_name": middle,
                "a_number": a_number,
            }.get(header_key, "")
            _set_widget_text(widget, value)
            continue

        classified = _classify_part9_entry_field(field_name)
        if classified is None:
            continue
        slot_index, field_id = classified
        if slot_index >= len(slot_values):
            continue
        _set_widget_text(widget, slot_values[slot_index].get(field_id, ""))


def _is_part9_continuation_widget(field_name: str) -> bool:
    lowered = field_name.lower()
    return "part2_" in lowered or "p10_line" in lowered


def _classify_part9_header_field(field_name: str) -> str | None:
    lowered = field_name.lower()
    if "part2_familyname" in lowered:
        return "family_name"
    if "part2_givenname" in lowered:
        return "given_name"
    if "part2_middlename" in lowered:
        return "middle_name"
    if "part2_line5_alienregistrationnumber" in lowered or "alienregistrationnumber" in lowered:
        return "a_number"
    return None


def _classify_part9_entry_field(field_name: str) -> tuple[int, str] | None:
    lowered = field_name.lower()
    match = _PART9_LINE_RE.search(lowered)
    if not match:
        return None
    try:
        line_number = int(match.group(1))
    except (TypeError, ValueError):
        return None
    if line_number < 2 or line_number > 5:
        return None
    slot_index = line_number - 2

    if "pagenumber" in lowered:
        return slot_index, "page_number"
    if "partnumber" in lowered:
        return slot_index, "part_number"
    if "itemnumber" in lowered:
        return slot_index, "item_number"
    if "additionalinfo" in lowered:
        return slot_index, "additional_information"
    return None


def _set_widget_text(widget: Any, value: str) -> bool:
    if not value:
        return True
    try:
        widget.field_value = value
        widget.update()
        return True
    except Exception as exc:
        log.warning(
            "Could not set Part 9 continuation widget %s to %r: %s",
            getattr(widget, "field_name", ""),
            value[:80],
            exc,
        )
        return False


def _format_a_number(value: Any) -> str:
    cleaned = _coerce_str(value)
    if not cleaned:
        return ""
    if cleaned.upper().startswith("A-"):
        return cleaned
    return f"A-{cleaned}"


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()
