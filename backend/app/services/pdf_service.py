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

# Storage directories (relative to backend/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"

for d in (UPLOADS_DIR, PAGES_DIR, THUMBNAILS_DIR):
    d.mkdir(parents=True, exist_ok=True)

THUMBNAIL_SIZE = (280, 360)
PAGE_DPI = 150  # resolution for full-page render


def _render_page_image(page: fitz.Page, dpi: int = PAGE_DPI) -> Image.Image:
    """Render a PyMuPDF page to a PIL Image."""
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=False)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


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

        # Full-size page image
        page_filename = f"{uuid.uuid4().hex}.png"
        page_path = PAGES_DIR / page_filename
        img.save(str(page_path), "PNG")

        # Thumbnail
        thumb = img.copy()
        thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
        thumb_filename = f"thumb_{page_filename}"
        thumb_path = THUMBNAILS_DIR / thumb_filename
        thumb.save(str(thumb_path), "PNG")

        results.append(
            {
                "page_number": page_num + 1,
                "file_path": str(page_path.relative_to(STORAGE_DIR)),
                "thumbnail_path": str(thumb_path.relative_to(STORAGE_DIR)),
            }
        )

    doc.close()
    return results


def process_image(upload_path: str) -> dict:
    """
    Process a standalone image (JPG, PNG, etc.) as a single page.

    Returns a dict: { "page_number": 1, "file_path": str, "thumbnail_path": str }
    """
    abs_path = STORAGE_DIR / upload_path
    img = Image.open(str(abs_path)).convert("RGB")

    # Full-size page image (copy into pages/ for uniformity)
    page_filename = f"{uuid.uuid4().hex}.png"
    page_path = PAGES_DIR / page_filename
    img.save(str(page_path), "PNG")

    # Thumbnail
    thumb = img.copy()
    thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    thumb_filename = f"thumb_{page_filename}"
    thumb_path = THUMBNAILS_DIR / thumb_filename
    thumb.save(str(thumb_path), "PNG")

    return {
        "page_number": 1,
        "file_path": str(page_path.relative_to(STORAGE_DIR)),
        "thumbnail_path": str(thumb_path.relative_to(STORAGE_DIR)),
    }

