"""
PDF / image processing service.

Responsibilities:
  - Split multi-page PDFs into individual page images.
  - Generate thumbnail images for each page.
  - Convert standalone images into single-page entries.

All file I/O goes through S3StorageService (no local disk writes).
"""

import io
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .paths import PAGES_PREFIX, THUMBNAILS_PREFIX, UPLOADS_PREFIX
from .rag_config import get_rag_settings
from .storage_service import S3StorageService

THUMBNAIL_SIZE = (280, 360)


def _render_page_image(page: fitz.Page, dpi: int | None = None) -> Image.Image:
    """Render a PyMuPDF page to a PIL Image."""
    if dpi is None:
        dpi = get_rag_settings().page_dpi
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _page_ext() -> str:
    settings = get_rag_settings()
    return ".jpg" if settings.page_image_format == "JPEG" else ".png"


def _image_to_bytes(img: Image.Image) -> bytes:
    """Serialize a PIL Image to bytes according to the configured format."""
    settings = get_rag_settings()
    buf = io.BytesIO()
    if settings.page_image_format == "JPEG":
        img.save(buf, "JPEG", quality=settings.page_image_quality, optimize=True)
    else:
        img.save(buf, "PNG")
    return buf.getvalue()


def _content_type() -> str:
    settings = get_rag_settings()
    return "image/jpeg" if settings.page_image_format == "JPEG" else "image/png"


def _save_page_and_thumbnail(img: Image.Image, s3: S3StorageService) -> dict[str, str]:
    """Upload a full-size page image and its thumbnail to S3, return relative keys."""
    ext = _page_ext()
    ct = _content_type()
    page_filename = f"{uuid.uuid4().hex}{ext}"

    page_key = f"{PAGES_PREFIX}/{page_filename}"
    s3.upload_bytes(_image_to_bytes(img), page_key, ct)

    thumb = img.copy()
    thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    thumb_key = f"{THUMBNAILS_PREFIX}/thumb_{page_filename}"
    s3.upload_bytes(_image_to_bytes(thumb), thumb_key, ct)

    return {"file_path": page_key, "thumbnail_path": thumb_key}


def save_uploaded_file(content: bytes, filename: str, s3: S3StorageService) -> str:
    """Upload a raw file to S3 and return its key."""
    ext = Path(filename).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    key = f"{UPLOADS_PREFIX}/{unique_name}"

    content_type = "application/pdf" if ext == ".pdf" else "application/octet-stream"
    s3.upload_bytes(content, key, content_type)
    return key


def split_pdf(upload_path: str, s3: S3StorageService) -> list[dict]:
    """
    Split a PDF into individual page images + thumbnails.

    Downloads the PDF from S3, processes in memory, uploads results back.
    Returns a list of dicts, one per page:
      { "page_number": int, "file_path": str, "thumbnail_path": str }
    """
    pdf_bytes = s3.download_bytes(upload_path)
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    results: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        img = _render_page_image(page)
        paths = _save_page_and_thumbnail(img, s3)
        results.append({"page_number": page_num + 1, **paths})

    doc.close()
    return results


def process_image(upload_path: str, s3: S3StorageService) -> dict:
    """
    Process a standalone image (JPG, PNG, etc.) as a single page.

    Downloads from S3, processes in memory, uploads results back.
    Returns a dict: { "page_number": 1, "file_path": str, "thumbnail_path": str }
    """
    img_bytes = s3.download_bytes(upload_path)
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    paths = _save_page_and_thumbnail(img, s3)
    return {"page_number": 1, **paths}
