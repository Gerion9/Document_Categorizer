"""S3 key prefixes used across services.

These replace the old local filesystem paths.  The actual STORAGE_DIR
constants are kept (but unused by new code) so that imports from modules
not yet migrated do not break at import time.
"""

from pathlib import Path

# ── S3 key prefixes (new) ─────────────────────────────────────────────────
UPLOADS_PREFIX = "uploads"
PAGES_PREFIX = "pages"
THUMBNAILS_PREFIX = "thumbnails"
EXPORTS_PREFIX = "exports"
FORMS_PREFIX = "formas"

# ── Legacy local paths (kept temporarily for services not yet migrated) ───
BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
PAGES_DIR = STORAGE_DIR / "pages"
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"
EXPORTS_DIR = STORAGE_DIR / "exports"

for _d in (UPLOADS_DIR, PAGES_DIR, THUMBNAILS_DIR, EXPORTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
