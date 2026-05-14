"""Google Document AI helpers for non-interactive PDF form detection."""

from __future__ import annotations

from pathlib import Path
import logging
import re
from typing import Any

import fitz  # PyMuPDF

from ..core.config import get_settings
from .storage_service import S3StorageService
from ..utils.text import clean_text as _clean_text

log = logging.getLogger("form_filling")

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def is_document_ai_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.GOOGLE_DOCUMENT_AI_PROJECT_ID
        and settings.GOOGLE_DOCUMENT_AI_LOCATION
        and settings.GOOGLE_DOCUMENT_AI_PROCESSOR_ID
    )


def _get_document_ai_client() -> tuple[Any, Any]:
    try:
        from google.api_core.client_options import ClientOptions
        from google.cloud import documentai
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-documentai is not installed. Add it to backend/requirements.txt."
        ) from exc

    settings = get_settings()
    location = settings.GOOGLE_DOCUMENT_AI_LOCATION or "us"
    client_options = None
    if location and location.lower() != "us":
        client_options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=client_options)
    return documentai, client


def _get_s3_service(explicit_s3: S3StorageService | None = None) -> S3StorageService | None:
    if explicit_s3 is not None:
        return explicit_s3
    try:
        from ..dependencies import get_s3_service

        return get_s3_service()
    except Exception as exc:  # pragma: no cover - depends on deployment config
        log.warning("Document AI S3 service unavailable: %s", exc)
        return None


def _read_pdf_bytes(pdf_path: str | Path, *, s3: S3StorageService | None = None) -> bytes:
    candidate = Path(pdf_path)
    if candidate.is_absolute() and candidate.exists():
        return candidate.read_bytes()
    if candidate.exists():
        return candidate.read_bytes()

    resolved_s3 = _get_s3_service(s3)
    if resolved_s3 is None:
        raise FileNotFoundError(f"Unable to resolve PDF path: {pdf_path}")
    return resolved_s3.download_bytes(str(pdf_path))


def _processor_name(client: Any) -> str:
    settings = get_settings()
    project_id = settings.GOOGLE_DOCUMENT_AI_PROJECT_ID
    location = settings.GOOGLE_DOCUMENT_AI_LOCATION or "us"
    processor_id = settings.GOOGLE_DOCUMENT_AI_PROCESSOR_ID
    processor_version = settings.GOOGLE_DOCUMENT_AI_PROCESSOR_VERSION
    if not project_id or not processor_id:
        raise RuntimeError("Google Document AI is not fully configured.")
    processor_name = client.processor_path(project_id, location, processor_id)
    if processor_version:
        return f"{processor_name}/processorVersions/{processor_version}"
    return processor_name


def _anchor_text(document_text: str, anchor: Any) -> str:
    if anchor is None:
        return ""
    segments = getattr(anchor, "text_segments", None) or []
    parts: list[str] = []
    for segment in segments:
        start = int(getattr(segment, "start_index", 0) or 0)
        end = int(getattr(segment, "end_index", 0) or 0)
        if end > start:
            parts.append(document_text[start:end])
    return _clean_text(" ".join(parts))


def _layout_text(document_text: str, layout_like: Any) -> str:
    layout = getattr(layout_like, "layout", layout_like)
    return _anchor_text(document_text, getattr(layout, "text_anchor", None))


def _layout_rect(layout_like: Any, page_rect: fitz.Rect) -> dict[str, float] | None:
    layout = getattr(layout_like, "layout", layout_like)
    bounding_poly = getattr(layout, "bounding_poly", None)
    if bounding_poly is None:
        return None

    normalized_vertices = list(getattr(bounding_poly, "normalized_vertices", []) or [])
    vertices = list(getattr(bounding_poly, "vertices", []) or [])
    points: list[tuple[float, float]] = []

    if normalized_vertices:
        for vertex in normalized_vertices:
            points.append((float(getattr(vertex, "x", 0.0)), float(getattr(vertex, "y", 0.0))))
        xs = [page_rect.x0 + (point[0] * page_rect.width) for point in points]
        ys = [page_rect.y0 + (point[1] * page_rect.height) for point in points]
    elif vertices:
        xs = [float(getattr(vertex, "x", 0.0)) for vertex in vertices]
        ys = [float(getattr(vertex, "y", 0.0)) for vertex in vertices]
    else:
        return None

    if not xs or not ys:
        return None
    return {
        "x0": round(min(xs), 2),
        "y0": round(min(ys), 2),
        "x1": round(max(xs), 2),
        "y1": round(max(ys), 2),
    }


def _slug(value: str) -> str:
    return _TOKEN_RE.sub("_", value.lower()).strip("_")


def _truncate_slug(slug: str, *, max_words: int = 6) -> str:
    """Keep the first few tokens so generated names remain readable."""
    parts = [part for part in slug.split("_") if part]
    if not parts:
        return ""
    return "_".join(parts[:max_words])


def _rect_centroid(rect: dict[str, float]) -> tuple[float, float]:
    return ((rect["x0"] + rect["x1"]) / 2.0, (rect["y0"] + rect["y1"]) / 2.0)


def _nearby_tokens_from_page(
    document_text: str,
    page: Any,
    page_rect: fitz.Rect,
    target_rect: dict[str, float],
    *,
    max_tokens: int = 5,
) -> str:
    """Return the closest text tokens to `target_rect` on a Document AI page.

    Used both for richer `nearby_text` and to derive a slug fallback when the
    Document AI field has no `field_name`. Prefers tokens that appear to the
    left of or above the target (typical label placement on USCIS forms).
    """
    target_cx, target_cy = _rect_centroid(target_rect)
    scored: list[tuple[float, str]] = []
    tokens = getattr(page, "tokens", None) or getattr(page, "lines", None) or []
    for token in tokens:
        rect = _layout_rect(token, page_rect)
        if rect is None:
            continue
        text = _layout_text(document_text, token)
        if not text or not text.strip():
            continue
        tcx, tcy = _rect_centroid(rect)
        dx = target_cx - tcx
        dy = target_cy - tcy
        # Prefer tokens to the left (dx>0) and slightly above (dy>0).
        bias = 0.0
        if dx > 0:
            bias -= 8.0
        if 0 < dy < 25:
            bias -= 4.0
        distance = (dx * dx + dy * dy) ** 0.5 + bias
        scored.append((distance, text.strip()))

    scored.sort(key=lambda item: item[0])
    chosen: list[str] = []
    for _, text in scored:
        if text in chosen:
            continue
        chosen.append(text)
        if len(chosen) >= max_tokens:
            break
    return " | ".join(chosen)


def _guess_field_type(field_label: str, value_text: str) -> str:
    combined = f"{field_label} {value_text}".lower()
    if value_text.lower() in {"selected", "unselected", "checked", "unchecked", "true", "false"}:
        return "checkbox"
    if any(token in combined for token in ("check box", "checkbox", "select this box", "mark this box")):
        return "checkbox"
    return "text"


def detect_form_fields_with_document_ai(
    pdf_path: str | Path,
    *,
    s3: S3StorageService | None = None,
) -> dict[str, Any]:
    """
    Detect field/value regions in a non-interactive PDF using Google Document AI.

    Returns the same normalized payload shape as `pdf_form_service.detect_form_fields`.
    """
    if not is_document_ai_configured():
        return {
            "pdf_path": str(pdf_path),
            "mode": "overlay",
            "has_acroform_fields": False,
            "needs_document_ai": True,
            "page_count": 0,
            "field_count": 0,
            "fields": [],
        }

    pdf_bytes = _read_pdf_bytes(pdf_path, s3=s3)
    pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        documentai, client = _get_document_ai_client()
        request = documentai.ProcessRequest(
            name=_processor_name(client),
            raw_document=documentai.RawDocument(content=pdf_bytes, mime_type="application/pdf"),
        )
        result = client.process_document(request=request)
        document = result.document
        document_text = getattr(document, "text", "") or ""

        fields: list[dict[str, Any]] = []
        seen_names: dict[str, int] = {}

        for page_index, page in enumerate(getattr(document, "pages", []) or []):
            page_number = page_index + 1
            pdf_page_rect = pdf_doc[page_index].rect if page_index < len(pdf_doc) else fitz.Rect(0, 0, 612, 792)

            for field_index, form_field in enumerate(getattr(page, "form_fields", []) or []):
                field_label = _layout_text(document_text, getattr(form_field, "field_name", None))
                value_text = _layout_text(document_text, getattr(form_field, "field_value", None))
                rect = _layout_rect(getattr(form_field, "field_value", None), pdf_page_rect) or _layout_rect(
                    getattr(form_field, "field_name", None),
                    pdf_page_rect,
                )
                if rect is None:
                    continue

                nearby_tokens = _nearby_tokens_from_page(
                    document_text,
                    page,
                    pdf_page_rect,
                    rect,
                )
                base_name = (
                    _truncate_slug(_slug(field_label))
                    or _truncate_slug(_slug(value_text))
                    or _truncate_slug(_slug(nearby_tokens))
                    or f"document_ai_field_{page_number}_{field_index + 1}"
                )
                seen_names[base_name] = seen_names.get(base_name, 0) + 1
                suffix = seen_names[base_name]
                field_name = base_name if suffix == 1 else f"{base_name}_{suffix}"
                field_type = _guess_field_type(field_label, value_text)
                nearby_parts = [part for part in (field_label, value_text, nearby_tokens) if part]
                nearby_text = _clean_text(" | ".join(nearby_parts))
                button_values = ["Yes"] if field_type == "checkbox" else []

                fields.append(
                    {
                        "field_name": field_name,
                        "field_label": field_label,
                        "field_type": field_type,
                        "field_type_hint": "button" if field_type == "checkbox" else "text",
                        "value": value_text,
                        "page_number": page_number,
                        "page_numbers": [page_number],
                        "rect": rect,
                        "rects": [rect],
                        "widget_count": 1,
                        "widget_xrefs": [],
                        "nearby_text": nearby_text,
                        "button_values": button_values,
                        "choice_values": [],
                        "field_flags": 0,
                    }
                )

        return {
            "pdf_path": str(pdf_path),
            "mode": "overlay_document_ai" if fields else "overlay",
            "has_acroform_fields": False,
            "needs_document_ai": False if fields else True,
            "page_count": len(pdf_doc),
            "field_count": len(fields),
            "fields": fields,
        }
    finally:
        pdf_doc.close()
