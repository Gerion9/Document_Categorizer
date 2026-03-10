"""
PDF / image processing service.

Responsibilities:
  - Split multi-page PDFs into individual page images.
  - Generate thumbnail images for each page.
  - Convert standalone images into single-page entries.
"""

import os
import uuid
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

from .paths import PAGES_DIR, STORAGE_DIR, THUMBNAILS_DIR, UPLOADS_DIR

THUMBNAIL_SIZE = (280, 360)
PAGE_DPI = int(os.getenv("PAGE_DPI", "150"))
PAGE_IMAGE_QUALITY = int(os.getenv("PAGE_IMAGE_QUALITY", "85"))
PAGE_IMAGE_FORMAT = os.getenv("PAGE_IMAGE_FORMAT", "JPEG").upper()


def _render_page_image(page: fitz.Page, dpi: int = PAGE_DPI) -> Image.Image:
    """Render a PyMuPDF page to a PIL Image."""
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _page_ext() -> str:
    return ".jpg" if PAGE_IMAGE_FORMAT == "JPEG" else ".png"


def _save_page_image(img: Image.Image, path: Path) -> None:
    if PAGE_IMAGE_FORMAT == "JPEG":
        img.save(str(path), "JPEG", quality=PAGE_IMAGE_QUALITY, optimize=True)
    else:
        img.save(str(path), "PNG")


def _save_page_and_thumbnail(img: Image.Image) -> dict[str, str]:
    """Save a full-size page image and its thumbnail, return relative paths."""
    ext = _page_ext()
    page_filename = f"{uuid.uuid4().hex}{ext}"
    page_path = PAGES_DIR / page_filename
    _save_page_image(img, page_path)

    thumb = img.copy()
    thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    thumb_path = THUMBNAILS_DIR / f"thumb_{page_filename}"
    _save_page_image(thumb, thumb_path)

    return {
        "file_path": str(page_path.relative_to(STORAGE_DIR)),
        "thumbnail_path": str(thumb_path.relative_to(STORAGE_DIR)),
    }


def save_uploaded_file(content: bytes, filename: str) -> str:
    """Persist an uploaded file and return the relative path inside storage/."""
    ext = Path(filename).suffix.lower()
    unique_name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / unique_name
    dest.write_bytes(content)
    return str(dest.relative_to(STORAGE_DIR))


def split_pdf(upload_path: str) -> list[dict]:
    """
    Split a PDF into individual page images + thumbnails.

    Returns a list of dicts, one per page:
      { "page_number": int, "file_path": str, "thumbnail_path": str }
    """
    abs_path = STORAGE_DIR / upload_path
    doc = fitz.open(str(abs_path))
    results: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        img = _render_page_image(page)
        paths = _save_page_and_thumbnail(img)
        results.append({"page_number": page_num + 1, **paths})

    doc.close()
    return results


def process_image(upload_path: str) -> dict:
    """
    Process a standalone image (JPG, PNG, etc.) as a single page.

    Returns a dict: { "page_number": 1, "file_path": str, "thumbnail_path": str }
    """
    abs_path = STORAGE_DIR / upload_path
    img = Image.open(str(abs_path)).convert("RGB")
    paths = _save_page_and_thumbnail(img)
    return {"page_number": 1, **paths}

