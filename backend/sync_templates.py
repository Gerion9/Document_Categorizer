"""Synchronize bundled form and QC templates into the configured database."""

from __future__ import annotations

import json

from app.database import SessionLocal
from app.services.template_sync_service import sync_all_templates


def main() -> None:
    with SessionLocal() as db:
        summary = sync_all_templates(db)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
