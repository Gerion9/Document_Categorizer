"""Utilities for reading and filling USCIS PDF forms with PyMuPDF."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import logging
from pathlib import Path
import re
import uuid
from typing import Any

import fitz  # PyMuPDF

from .document_ai_form_service import detect_form_fields_with_document_ai
from .paths import EXPORTS_DIR, EXPORTS_PREFIX, STORAGE_DIR
from .storage_service import S3StorageService
from ..utils.text import clean_text as _clean_text

_NEARBY_FOOTER_RE = re.compile(r"^(?:page\s+\d+(?:\s+of\s+\d+)?|\d+)$", re.IGNORECASE)
_NEARBY_HEADING_RE = re.compile(r"^(?:part|section|item|subpart)\b", re.IGNORECASE)
_PDF_NAME_ESCAPE_RE = re.compile(r"#([0-9A-Fa-f]{2})")
log = logging.getLogger("form_filling")

def _get_s3_service(explicit_s3: S3StorageService | None = None) -> S3StorageService | None:
    if explicit_s3 is not None:
        return explicit_s3
    try:
        from ..dependencies import get_s3_service

        return get_s3_service()
    except Exception:
        return None

def _resolve_pdf_path(pdf_path: str | Path) -> Path:
    candidate = Path(pdf_path)
    return candidate if candidate.is_absolute() else (STORAGE_DIR / candidate)

def _read_pdf_bytes(pdf_path: str | Path, *, s3: S3StorageService | None = None) -> tuple[bytes, bool]:
    candidate = _resolve_pdf_path(pdf_path)
    if candidate.exists():
        return candidate.read_bytes(), False

    resolved_s3 = _get_s3_service(s3)
    if resolved_s3 is None:
        raise FileNotFoundError(f"Unable to resolve PDF path: {pdf_path}")
    return resolved_s3.download_bytes(str(pdf_path)), True

def _ensure_output_path(
    output_path: str | Path | None,
    *,
    source_path: str | Path,
    suffix: str = "_filled",
    prefer_s3: bool = False,
) -> tuple[Path | str, bool]:
    source_name = Path(str(source_path))
    if output_path:
        candidate = Path(output_path)
        if candidate.is_absolute():
            candidate.parent.mkdir(parents=True, exist_ok=True)
            return candidate, False
        normalized = str(output_path).replace("\\", "/").strip("/")
        return normalized, True
    else:
        filename = f"{source_name.stem}{suffix}_{uuid.uuid4().hex[:8]}{source_name.suffix or '.pdf'}"
        if prefer_s3:
            return f"{EXPORTS_PREFIX}/{filename}", True
        candidate = EXPORTS_DIR / filename
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate, False


def _write_output_pdf(
    doc: fitz.Document,
    output_path: Path | str,
    *,
    use_s3: bool,
    s3: S3StorageService | None = None,
) -> str:
    pdf_bytes = doc.tobytes()
    if use_s3:
        resolved_s3 = _get_s3_service(s3)
        if resolved_s3 is None:
            raise RuntimeError("S3 storage is required to persist the filled PDF.")
        resolved_s3.upload_bytes(pdf_bytes, str(output_path), "application/pdf")
        return str(output_path)

    candidate = Path(output_path)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if candidate.exists():
        candidate.unlink()
    candidate.write_bytes(pdf_bytes)
    return _storage_relative(candidate)


def _storage_relative(path: Path) -> str:
    try:
        return str(path.relative_to(STORAGE_DIR))
    except ValueError:
        return str(path)


def _iter_widgets(page: fitz.Page) -> list[Any]:
    widgets = page.widgets()
    if widgets is None:
        return []
    return list(widgets)


def _field_type_name(widget: Any) -> str:
    raw_name = _clean_text(getattr(widget, "field_type_string", ""))
    lowered = raw_name.lower()
    if "signature" in lowered:
        return "signature"
    if "combo" in lowered or "list" in lowered or "choice" in lowered:
        return "choice"
    if "radio" in lowered:
        return "radio"
    if "check" in lowered:
        return "checkbox"
    if "button" in lowered:
        return "button"
    if "text" in lowered:
        return "text"

    field_type = getattr(widget, "field_type", None)
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_TEXT", object()):
        return "text"
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_CHECKBOX", object()):
        return "checkbox"
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_RADIOBUTTON", object()):
        return "radio"
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_LISTBOX", object()):
        return "choice"
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_COMBOBOX", object()):
        return "choice"
    if field_type == getattr(fitz, "PDF_WIDGET_TYPE_SIGNATURE", object()):
        return "signature"
    return lowered or "unknown"


def _field_type_hint(field_type: str) -> str:
    lowered = (field_type or "").lower()
    if lowered in {"checkbox", "radio", "button"}:
        return "button"
    if lowered in {"choice", "combobox", "listbox", "select"}:
        return "choice"
    if lowered == "signature":
        return "signature"
    return "text"


def _extract_button_values(widget: Any) -> list[str]:
    button_states = getattr(widget, "button_states", None)
    if not callable(button_states):
        return []

    try:
        raw = button_states() or {}
    except Exception:
        return []

    values: list[str] = []
    if isinstance(raw, dict):
        for state_values in raw.values():
            if isinstance(state_values, (list, tuple, set)):
                values.extend(_clean_text(v) for v in state_values if _clean_text(v))
            else:
                cleaned = _clean_text(state_values)
                if cleaned:
                    values.append(cleaned)
    elif isinstance(raw, (list, tuple, set)):
        values.extend(_clean_text(v) for v in raw if _clean_text(v))

    deduped: list[str] = []
    for value in values:
        if value not in deduped and value.lower() != "off":
            deduped.append(value)
    return deduped


def _decode_pdf_name_escapes(value: Any) -> str:
    cleaned = _clean_text(value)
    if "#" not in cleaned:
        return cleaned

    def replace(match: re.Match[str]) -> str:
        try:
            return bytes.fromhex(match.group(1)).decode("latin-1")
        except ValueError:
            return match.group(0)

    return _PDF_NAME_ESCAPE_RE.sub(replace, cleaned)


def _normalize_button_value(value: Any) -> str:
    decoded = _decode_pdf_name_escapes(value).lower()
    return re.sub(r"[^a-z0-9]+", "", decoded)


def _extract_choice_values(widget: Any) -> list[str]:
    raw_values = getattr(widget, "choice_values", None)
    if not isinstance(raw_values, (list, tuple, set)):
        return []

    values: list[str] = []
    for value in raw_values:
        if isinstance(value, (list, tuple)) and len(value) >= 1:
            cleaned = _clean_text(value[0])
        else:
            cleaned = _clean_text(value)
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _rect_vertical_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = left & right
    if overlap.is_empty:
        return 0.0
    return max(0.0, min(1.0, float(overlap.height) / max(1.0, min(left.height, right.height))))


def _rect_horizontal_overlap_ratio(left: fitz.Rect, right: fitz.Rect) -> float:
    overlap = left & right
    if overlap.is_empty:
        return 0.0
    return max(0.0, min(1.0, float(overlap.width) / max(1.0, min(left.width, right.width))))


def _is_useful_nearby_text(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned or len(cleaned) < 2:
        return False
    if _NEARBY_FOOTER_RE.fullmatch(cleaned):
        return False
    if len(re.findall(r"[A-Za-z0-9]", cleaned)) < max(2, int(len(cleaned) * 0.25)):
        return False
    return True


def _truncate_nearby_snippet(text: str, *, max_chars: int = 180) -> str:
    cleaned = _clean_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _page_text_lines(page: fitz.Page) -> list[dict[str, Any]]:
    try:
        raw_words = page.get_text("words") or []
    except Exception:
        return []

    grouped: dict[tuple[int, int], list[tuple[int, str, fitz.Rect]]] = {}
    for word in raw_words:
        if len(word) < 8:
            continue
        x0, y0, x1, y1, raw_text, block_no, line_no, word_no = word[:8]
        text = _clean_text(raw_text)
        if not text:
            continue
        grouped.setdefault((int(block_no), int(line_no)), []).append(
            (int(word_no), text, fitz.Rect(float(x0), float(y0), float(x1), float(y1)))
        )

    lines: list[dict[str, Any]] = []
    for (block_no, line_no), entries in grouped.items():
        entries.sort(key=lambda item: item[0])
        text = " ".join(item[1] for item in entries if item[1]).strip()
        if not _is_useful_nearby_text(text):
            continue
        rect = fitz.Rect(entries[0][2])
        for _, _, word_rect in entries[1:]:
            rect |= word_rect
        lines.append(
            {
                "text": _truncate_nearby_snippet(text),
                "rect": rect,
                "block_no": block_no,
                "line_no": line_no,
            }
        )

    lines.sort(key=lambda item: (round(float(item["rect"].y0), 2), round(float(item["rect"].x0), 2)))
    return lines


def _score_nearby_line(line: Mapping[str, Any], widget_rect: fitz.Rect, page_rect: fitz.Rect) -> float:
    text = _clean_text(line.get("text"))
    line_rect = line.get("rect")
    if not text or not isinstance(line_rect, fitz.Rect):
        return 0.0

    line_center_y = (float(line_rect.y0) + float(line_rect.y1)) / 2
    widget_center_y = (float(widget_rect.y0) + float(widget_rect.y1)) / 2
    center_gap_y = abs(line_center_y - widget_center_y)
    left_gap = float(widget_rect.x0) - float(line_rect.x1)
    right_gap = float(line_rect.x0) - float(widget_rect.x1)
    vertical_overlap = _rect_vertical_overlap_ratio(line_rect, widget_rect)
    horizontal_overlap = _rect_horizontal_overlap_ratio(line_rect, widget_rect)
    vertical_gap = float(widget_rect.y0) - float(line_rect.y1)
    heading_match = bool(_NEARBY_HEADING_RE.match(text))
    expanded_band = fitz.Rect(widget_rect.x0 - 140, widget_rect.y0, widget_rect.x1 + 140, widget_rect.y1) & page_rect
    band_overlap = _rect_horizontal_overlap_ratio(line_rect, expanded_band)

    score = 0.0

    if vertical_overlap >= 0.45 or center_gap_y <= 12:
        if -24 <= left_gap <= 280:
            score = max(score, 4.2 - (max(0.0, left_gap) * 0.012))
        if -24 <= right_gap <= 280:
            score = max(score, 4.0 - (max(0.0, right_gap) * 0.012))
        if horizontal_overlap >= 0.3:
            score = max(score, 3.3 + (0.3 * vertical_overlap))

    if 0 <= vertical_gap <= 96:
        score = max(score, 2.2 + (0.7 * band_overlap) - (vertical_gap * 0.018))
        if heading_match:
            score += 0.35

    if heading_match and 0 <= vertical_gap <= 180:
        score = max(score, 1.8 - (vertical_gap * 0.01))

    return round(max(0.0, min(5.0, score)), 4)


def _collect_nearby_snippets_from_lines(
    lines: list[dict[str, Any]],
    widget_rect: fitz.Rect,
    page_rect: fitz.Rect,
    *,
    max_snippets: int = 6,
) -> list[str]:
    scored: list[tuple[float, str, fitz.Rect]] = []
    for line in lines:
        text = _clean_text(line.get("text"))
        line_rect = line.get("rect")
        if not text or not isinstance(line_rect, fitz.Rect):
            continue
        score = _score_nearby_line(line, widget_rect, page_rect)
        if score <= 0:
            continue
        scored.append((score, _truncate_nearby_snippet(text), line_rect))

    scored.sort(key=lambda item: (-item[0], float(item[2].y0), float(item[2].x0)))
    snippets: list[str] = []
    for _, snippet, _ in scored:
        if snippet and snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= max_snippets:
            break
    return snippets


def _extract_nearby_text_from_clips(page: fitz.Page, rect: fitz.Rect) -> str:
    candidate_clips = [
        fitz.Rect(rect.x0 - 240, rect.y0 - 10, rect.x0 - 2, rect.y1 + 10) & page.rect,
        fitz.Rect(rect.x1 + 2, rect.y0 - 10, rect.x1 + 240, rect.y1 + 10) & page.rect,
        fitz.Rect(rect.x0 - 36, rect.y0 - 34, rect.x1 + 36, rect.y0 - 2) & page.rect,
        fitz.Rect(rect.x0 - 280, rect.y0 - 12, rect.x1 + 280, rect.y1 + 12) & page.rect,
        fitz.Rect(36, max(0.0, rect.y0 - 140), max(36.0, page.rect.x1 - 36), rect.y0 - 16) & page.rect,
    ]
    snippets: list[str] = []
    for clip in candidate_clips:
        try:
            if clip.is_empty or clip.get_area() <= 1:
                continue
            snippet = _clean_text(page.get_text("text", clip=clip))
        except Exception:
            continue
        if not _is_useful_nearby_text(snippet):
            continue
        normalized = _truncate_nearby_snippet(snippet)
        if normalized and normalized not in snippets:
            snippets.append(normalized)
    return " | ".join(snippets[:5])


def _extract_nearby_text(
    page: fitz.Page,
    rect: fitz.Rect,
    *,
    page_text_lines: list[dict[str, Any]] | None = None,
) -> str:
    snippets = _collect_nearby_snippets_from_lines(page_text_lines or _page_text_lines(page), rect, page.rect)
    if snippets:
        return " | ".join(snippets)
    return _extract_nearby_text_from_clips(page, rect)


def _rect_to_dict(rect: fitz.Rect) -> dict[str, float]:
    return {
        "x0": round(float(rect.x0), 2),
        "y0": round(float(rect.y0), 2),
        "x1": round(float(rect.x1), 2),
        "y1": round(float(rect.y1), 2),
    }


def extract_pdf_text(pdf_path: str | Path, *, max_pages: int | None = None) -> str:
    """Extract plain text from a PDF using embedded text content."""
    pdf_bytes, _ = _read_pdf_bytes(pdf_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_total = len(doc) if max_pages is None else min(len(doc), max_pages)
        chunks: list[str] = []
        for page_index in range(page_total):
            text = _clean_text(doc[page_index].get_text("text"))
            if text:
                chunks.append(text)
        return "\n\n".join(chunks).strip()
    finally:
        doc.close()


def detect_form_fields(pdf_path: str | Path) -> dict[str, Any]:
    """
    Detect logical AcroForm fields from a PDF.

    Returns a normalized payload that aggregates repeated widgets sharing the
    same `field_name`, which is common in official USCIS forms.
    """
    pdf_bytes, used_s3 = _read_pdf_bytes(pdf_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        page_count = len(doc)
        fields_by_name: dict[str, dict[str, Any]] = {}
        unnamed_counter = 0

        for page_index in range(page_count):
            page = doc[page_index]
            page_number = page_index + 1
            page_text_lines = _page_text_lines(page)

            for widget_index, widget in enumerate(_iter_widgets(page)):
                field_name = _clean_text(getattr(widget, "field_name", ""))
                if not field_name:
                    unnamed_counter += 1
                    field_name = f"unnamed_field_{page_number}_{widget_index}_{unnamed_counter}"

                field_label = _clean_text(getattr(widget, "field_label", ""))
                field_type = _field_type_name(widget)
                nearby_text = _extract_nearby_text(page, widget.rect, page_text_lines=page_text_lines)
                entry = fields_by_name.get(field_name)

                if entry is None:
                    entry = {
                        "field_name": field_name,
                        "field_label": field_label,
                        "field_type": field_type,
                        "field_type_hint": _field_type_hint(field_type),
                        "value": _clean_text(getattr(widget, "field_value", "")),
                        "page_number": page_number,
                        "page_numbers": [page_number],
                        "rect": _rect_to_dict(widget.rect),
                        "rects": [_rect_to_dict(widget.rect)],
                        "widget_count": 0,
                        "widget_xrefs": [],
                        "nearby_text": nearby_text,
                        "button_values": [],
                        "choice_values": [],
                        "field_flags": getattr(widget, "field_flags", 0) or 0,
                    }
                    fields_by_name[field_name] = entry

                entry["widget_count"] += 1

                xref = getattr(widget, "xref", None)
                if isinstance(xref, int) and xref not in entry["widget_xrefs"]:
                    entry["widget_xrefs"].append(xref)

                if page_number not in entry["page_numbers"]:
                    entry["page_numbers"].append(page_number)

                rect_dict = _rect_to_dict(widget.rect)
                if rect_dict not in entry["rects"]:
                    entry["rects"].append(rect_dict)

                if field_label and not entry["field_label"]:
                    entry["field_label"] = field_label

                current_value = _clean_text(getattr(widget, "field_value", ""))
                if current_value and not entry["value"]:
                    entry["value"] = current_value

                if nearby_text:
                    snippets = [s for s in entry["nearby_text"].split(" | ") if s]
                    if nearby_text not in snippets:
                        snippets.append(nearby_text)
                    entry["nearby_text"] = " | ".join(snippets[:4])

                for button_value in _extract_button_values(widget):
                    if button_value not in entry["button_values"]:
                        entry["button_values"].append(button_value)

                for choice_value in _extract_choice_values(widget):
                    if choice_value not in entry["choice_values"]:
                        entry["choice_values"].append(choice_value)

        fields = sorted(
            fields_by_name.values(),
            key=lambda item: (item.get("page_number") or 0, item.get("field_name") or ""),
        )
        if fields:
            return {
                "pdf_path": str(pdf_path),
                "mode": "acroform",
                "has_acroform_fields": True,
                "needs_document_ai": False,
                "page_count": page_count,
                "field_count": len(fields),
                "fields": fields,
            }
    finally:
        doc.close()

    if used_s3:
        document_ai_result = detect_form_fields_with_document_ai(pdf_path, s3=_get_s3_service())
    else:
        document_ai_result = detect_form_fields_with_document_ai(pdf_path)

    if document_ai_result.get("field_count"):
        if not document_ai_result.get("page_count"):
            document_ai_result["page_count"] = page_count
        return document_ai_result

    return {
        "pdf_path": str(pdf_path),
        "mode": "overlay",
        "has_acroform_fields": False,
        "needs_document_ai": True,
        "page_count": page_count,
        "field_count": 0,
        "fields": [],
    }


def read_form_fields(pdf_path: str | Path) -> list[dict[str, Any]]:
    """Convenience wrapper that returns only the normalized field list."""
    return detect_form_fields(pdf_path)["fields"]


def _coerce_field_value_map(field_values: Mapping[str, Any] | Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    if isinstance(field_values, Mapping):
        normalized: dict[str, Any] = {}
        for raw_name, raw_value in field_values.items():
            field_name = _clean_text(raw_name)
            if not field_name:
                continue
            if isinstance(raw_value, Mapping):
                normalized[field_name] = (
                    raw_value.get("value")
                    if "value" in raw_value
                    else raw_value.get("field_value", raw_value.get("extracted_value"))
                )
            else:
                normalized[field_name] = raw_value
        return normalized

    normalized: dict[str, Any] = {}
    for item in field_values:
        if not isinstance(item, Mapping):
            continue
        field_name = _clean_text(item.get("field_name"))
        if not field_name:
            continue
        normalized[field_name] = (
            item.get("value")
            if "value" in item
            else item.get("field_value", item.get("extracted_value"))
        )
    return normalized


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    lowered = _clean_text(value).lower()
    return lowered in {"1", "true", "yes", "y", "on", "checked", "x"}


def _button_target_value(widget: Any, value: Any) -> str:
    on_values = _extract_button_values(widget)
    lowered = _clean_text(value).lower()
    normalized_value = _normalize_button_value(value)

    if lowered in {"off", "false", "0", "no", "unchecked", ""}:
        return "Off"

    for candidate in on_values:
        if candidate.lower() == lowered:
            return "Yes"
        if normalized_value and _normalize_button_value(candidate) == normalized_value:
            return "Yes"

    if lowered in {"true", "1", "yes", "y", "on", "checked", "x"}:
        return "Yes"

    if isinstance(value, str) and _clean_text(value):
        return _clean_text(value)

    return on_values[0] if _is_truthy(value) else "Off"


def _is_bad_choice_field_error(exc: Exception) -> bool:
    return "bad choice field list" in _clean_text(str(exc)).lower()


def _repair_and_set_choice_field(widget: Any, value: Any) -> bool:
    """Attempt to fix a malformed choice field by rebuilding its option list,
    then set the value.  Returns True on success."""
    try:
        raw_choices = getattr(widget, "choice_values", None) or []
        cleaned: list[str] = []
        for item in raw_choices:
            if isinstance(item, (list, tuple)) and len(item) >= 1:
                cleaned.append(str(item[0]).strip())
            else:
                cleaned.append(str(item).strip())
        widget.choice_values = cleaned
        widget.field_value = "" if value is None else str(value)
        widget.update()
        return True
    except Exception:
        return False


def _force_disable_need_appearances(doc: "fitz.Document") -> None:
    """Ensure the output PDF never carries ``/NeedAppearances true``.

    Some USCIS templates (notably the I-914) declare each page's PDF417
    barcode as a plain Text widget whose visible barcode lives only in its
    pre-baked ``/AP`` appearance stream. When ``/NeedAppearances`` is true,
    viewers discard ``/AP`` and regenerate the appearance from ``/V``, which
    turns the barcode into the literal text the value contains. We rely on
    PyMuPDF's ``widget.update()`` for per-widget appearance regeneration on
    the fields we actually write, so this global flag is both unnecessary and
    harmful.
    """
    try:
        catalog_xref = doc.pdf_catalog()
        acroform_ref = doc.xref_get_key(catalog_xref, "AcroForm")
    except Exception:
        return

    if not acroform_ref or acroform_ref[0] != "xref":
        return

    try:
        acroform_xref = int(str(acroform_ref[1]).split()[0])
    except (TypeError, ValueError):
        return

    try:
        doc.xref_set_key(acroform_xref, "NeedAppearances", "false")
    except Exception:
        pass


def fill_acroform_fields(
    pdf_path: str | Path,
    field_values: Mapping[str, Any] | Iterable[Mapping[str, Any]],
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Write values into AcroForm widgets and save a new filled PDF."""
    abs_input = _resolve_pdf_path(pdf_path)
    input_bytes, input_uses_s3 = _read_pdf_bytes(pdf_path)
    abs_output, output_uses_s3 = _ensure_output_path(
        output_path,
        source_path=pdf_path,
        prefer_s3=input_uses_s3,
    )
    if not input_uses_s3 and not output_uses_s3 and abs_input.resolve() == Path(abs_output).resolve():
        raise ValueError("Output PDF path must be different from the source PDF path.")

    value_map = _coerce_field_value_map(field_values)
    doc = fitz.open(stream=input_bytes, filetype="pdf")
    try:
        _force_disable_need_appearances(doc)

        written_fields: set[str] = set()
        skipped_fields: set[str] = set()

        for page_index in range(len(doc)):
            page = doc[page_index]
            for widget in _iter_widgets(page):
                field_name = _clean_text(getattr(widget, "field_name", ""))
                if not field_name or field_name not in value_map:
                    continue

                field_type = _field_type_name(widget)
                value = value_map[field_name]

                try:
                    if field_type in {"checkbox", "radio", "button"}:
                        widget.field_value = _button_target_value(widget, value)
                    else:
                        widget.field_value = "" if value is None else str(value)

                    widget.update()
                    written_fields.add(field_name)
                except Exception as exc:
                    if field_type == "choice" and _is_bad_choice_field_error(exc):
                        if _repair_and_set_choice_field(widget, value):
                            written_fields.add(field_name)
                            continue
                        skipped_fields.add(field_name)
                        log.warning(
                            "Skipping malformed choice field during PDF fill "
                            "field=%s page=%s value=%r options=%r error=%s",
                            field_name,
                            page_index + 1,
                            value,
                            _extract_choice_values(widget),
                            str(exc),
                        )
                        continue
                    raise

        # Remove the NeedAppearances flag before saving so PDF viewers
        # do NOT regenerate appearance streams for untouched fields.
        # Barcode widgets (PDF417) carry a pre-rendered appearance that
        # the viewer cannot recreate; leaving the flag would cause it to
        # replace the barcode image with the raw field value as text.
        try:
            doc.need_appearances(False)
        except Exception:
            pass

        resolved_output = _write_output_pdf(
            doc,
            abs_output,
            use_s3=output_uses_s3,
            s3=_get_s3_service(),
        )

        skipped_field_names = skipped_fields - written_fields
        missing_fields = sorted((set(value_map) - written_fields) | skipped_field_names)
        return {
            "output_path": resolved_output,
            "written_count": len(written_fields),
            "missing_fields": missing_fields,
            "skipped_fields": sorted(skipped_field_names),
            "field_count": len(value_map),
        }
    finally:
        doc.close()


def _coerce_rect(item: Mapping[str, Any]) -> fitz.Rect:
    raw_rect = item.get("rect")
    if isinstance(raw_rect, fitz.Rect):
        return raw_rect
    if isinstance(raw_rect, Mapping):
        return fitz.Rect(
            float(raw_rect["x0"]),
            float(raw_rect["y0"]),
            float(raw_rect["x1"]),
            float(raw_rect["y1"]),
        )
    if isinstance(raw_rect, (list, tuple)) and len(raw_rect) == 4:
        return fitz.Rect(float(raw_rect[0]), float(raw_rect[1]), float(raw_rect[2]), float(raw_rect[3]))

    x0 = item.get("x0", item.get("x"))
    y0 = item.get("y0", item.get("y"))
    x1 = item.get("x1")
    y1 = item.get("y1")
    if x1 is None and x0 is not None and item.get("width") is not None:
        x1 = float(x0) + float(item["width"])
    if y1 is None and y0 is not None and item.get("height") is not None:
        y1 = float(y0) + float(item["height"])
    if None in {x0, y0, x1, y1}:
        raise ValueError("Overlay field is missing rectangle coordinates.")
    return fitz.Rect(float(x0), float(y0), float(x1), float(y1))


def fill_overlay_fields(
    pdf_path: str | Path,
    field_positions_and_values: Iterable[Mapping[str, Any]],
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """
    Overlay text or simple X marks on top of a non-interactive PDF.

    Expected item keys:
      - `page_number` (1-based)
      - either `rect` or rectangle coordinates
      - `value`
      - optional `field_type`, `font_size`, `font_name`
    """
    abs_input = _resolve_pdf_path(pdf_path)
    input_bytes, input_uses_s3 = _read_pdf_bytes(pdf_path)
    abs_output, output_uses_s3 = _ensure_output_path(
        output_path,
        source_path=pdf_path,
        suffix="_overlay",
        prefer_s3=input_uses_s3,
    )
    if not input_uses_s3 and not output_uses_s3 and abs_input.resolve() == Path(abs_output).resolve():
        raise ValueError("Output PDF path must be different from the source PDF path.")

    doc = fitz.open(stream=input_bytes, filetype="pdf")
    try:
        written_count = 0
        for item in field_positions_and_values:
            page_number = int(item.get("page_number") or 0)
            if page_number <= 0 or page_number > len(doc):
                raise ValueError(f"Invalid page_number for overlay field: {page_number}")

            page = doc[page_number - 1]
            rect = _coerce_rect(item)
            value = item.get("value", "")
            field_type = _clean_text(item.get("field_type", "text")).lower()

            if field_type in {"checkbox", "radio", "button"}:
                if _is_truthy(value):
                    page.insert_textbox(
                        rect,
                        "X",
                        fontname=str(item.get("font_name") or "helv"),
                        fontsize=float(item.get("font_size") or 10),
                        color=(0, 0, 0),
                        align=1,
                    )
                    written_count += 1
                continue

            text_value = _clean_text(value)
            if not text_value:
                continue

            page.insert_textbox(
                rect,
                text_value,
                fontname=str(item.get("font_name") or "helv"),
                fontsize=float(item.get("font_size") or 10),
                color=(0, 0, 0),
            )
            written_count += 1

        resolved_output = _write_output_pdf(
            doc,
            abs_output,
            use_s3=output_uses_s3,
            s3=_get_s3_service(),
        )

        return {
            "output_path": resolved_output,
            "written_count": written_count,
        }
    finally:
        doc.close()


def draw_label_adjacent_text(
    pdf_path: str | Path,
    entries: Iterable[Mapping[str, Any]],
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Draw free-form text anchored to an existing static label in the PDF.

    This is used for "blank space" areas of the form that have no AcroForm
    widget to fill. The function locates the label text on the requested
    page and draws `value` at a rectangle computed by applying offsets
    and a width/height to the label's rectangle.

    Each entry accepts these keys:
      - ``page_number`` (1-based) [required]
      - ``label_text`` (exact label string to search for) [required]
      - ``value`` (text to render) [required, skipped if empty]
      - ``occurrence`` (int, 0-based index to pick when the label appears
        multiple times on the page; default 0)
      - ``anchor_y`` (float, preferred Y; picks the label match closest to it)
      - ``offset_x``, ``offset_y`` (floats, applied to the label rect top-left)
      - ``width``, ``height`` (floats, rectangle size; default 300 x 14)
      - ``font_size`` (float, default 9)
      - ``font_name`` (str, default "helv")
      - ``align`` (int, default 0 left-align)
    """
    input_bytes, input_uses_s3 = _read_pdf_bytes(pdf_path)
    abs_input = _resolve_pdf_path(pdf_path)
    abs_output, output_uses_s3 = _ensure_output_path(
        output_path,
        source_path=pdf_path,
        suffix="_label_overlay",
        prefer_s3=input_uses_s3,
    )
    if not input_uses_s3 and not output_uses_s3 and abs_input.resolve() == Path(abs_output).resolve():
        raise ValueError("Output PDF path must be different from the source PDF path.")

    doc = fitz.open(stream=input_bytes, filetype="pdf")
    try:
        written_count = 0
        skipped: list[dict[str, Any]] = []

        for entry in entries:
            value = _clean_text(entry.get("value"))
            if not value:
                continue

            page_number = int(entry.get("page_number") or 0)
            if page_number <= 0 or page_number > len(doc):
                skipped.append({"reason": "invalid_page", "entry": dict(entry)})
                continue
            page = doc[page_number - 1]

            label_text = _clean_text(entry.get("label_text"))
            if not label_text:
                skipped.append({"reason": "missing_label", "entry": dict(entry)})
                continue

            matches = page.search_for(label_text) or []
            if not matches:
                skipped.append({"reason": "label_not_found", "entry": dict(entry)})
                log.warning(
                    "draw_label_adjacent_text: label %r not found on page %d",
                    label_text,
                    page_number,
                )
                continue

            anchor_y = entry.get("anchor_y")
            if anchor_y is not None:
                try:
                    anchor_y_value = float(anchor_y)
                except (TypeError, ValueError):
                    anchor_y_value = None
                if anchor_y_value is not None:
                    matches = sorted(matches, key=lambda r: abs(r.y0 - anchor_y_value))
            else:
                occurrence = int(entry.get("occurrence") or 0)
                if 0 <= occurrence < len(matches):
                    matches = matches[occurrence:] + matches[:occurrence]

            label_rect = matches[0]

            offset_x = float(entry.get("offset_x") or 0.0)
            offset_y = float(entry.get("offset_y") or 0.0)
            width = float(entry.get("width") or 300.0)
            height = float(entry.get("height") or 14.0)

            x0 = float(label_rect.x0) + offset_x
            y0 = float(label_rect.y0) + offset_y
            draw_rect = fitz.Rect(x0, y0, x0 + width, y0 + height)

            page.insert_textbox(
                draw_rect,
                value,
                fontname=str(entry.get("font_name") or "helv"),
                fontsize=float(entry.get("font_size") or 9),
                color=(0, 0, 0),
                align=int(entry.get("align") or 0),
            )
            written_count += 1

        resolved_output = _write_output_pdf(
            doc,
            abs_output,
            use_s3=output_uses_s3,
            s3=_get_s3_service(),
        )

        return {
            "output_path": resolved_output,
            "written_count": written_count,
            "skipped": skipped,
        }
    finally:
        doc.close()