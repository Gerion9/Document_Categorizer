"""Single source of truth for filesystem paths used across services."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"
EXPORTS_DIR = STORAGE_DIR / "exports"

for _d in (UPLOADS_DIR, PAGES_DIR, THUMBNAILS_DIR, EXPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
