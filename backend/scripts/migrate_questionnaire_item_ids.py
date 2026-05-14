"""Remap historic `questionnaire_item_id` values stored in the database.

When a questionnaire JSON renames an item id (for example, when migrating
positional ids like ``p2_27`` to semantic ids like ``p2_eligibility_category``),
historical rows in tables that store the old id need to be updated so that
prior cases keep their links to the questionnaire definitions.

This script applies a static mapping declared in ``MAPPINGS`` below. The dict
is intentionally empty by default: the current canonical questionnaire JSONs
do NOT contain positional ids (all are semantic snake_case). Future renames
should populate ``MAPPINGS`` here and run this script once after deploying the
new JSON.

Affected tables (whitelisted):
- ``questionnaire_answer.question_id`` (canonical ``<item_id>`` or
  ``<item_id>.<field_id>``).
- ``form_filling_field.questionnaire_item_id``.
- ``form_filling_field.canonical_questionnaire_id``.

Usage:
    python -m scripts.migrate_questionnaire_item_ids --check  # report only
    python -m scripts.migrate_questionnaire_item_ids --apply  # commit changes
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal


# Add entries here when renaming a questionnaire id, e.g.
#   {("i-765", "p2_27"): "p2_eligibility_category"}
# A None value drops the row (use carefully). The tuple is (form_type, old_id).
MAPPINGS: dict[tuple[str, str], str | None] = {}


def _iter_mappings_for_table(table: str) -> Iterable[tuple[str, str, str]]:
    """Yield (form_type, old_id, new_id) tuples; deletions are emitted last."""
    for (form_type, old_id), new_id in MAPPINGS.items():
        if new_id is None:
            continue
        yield (form_type, old_id, new_id)


def _apply_to_table(db: Session, table: str, id_column: str, apply: bool) -> int:
    updated = 0
    for form_type, old_id, new_id in _iter_mappings_for_table(table):
        params = {"form_type": form_type, "old_id": old_id, "new_id": new_id}
        sql = text(
            f"UPDATE {table} SET {id_column} = :new_id "
            f"WHERE form_type = :form_type AND {id_column} = :old_id"
        )
        if apply:
            result = db.execute(sql, params)
            updated += result.rowcount or 0
            print(f"  [apply] {table}.{id_column}: {form_type} {old_id!r} -> {new_id!r} ({result.rowcount} rows)")
        else:
            count_sql = text(
                f"SELECT COUNT(*) FROM {table} "
                f"WHERE form_type = :form_type AND {id_column} = :old_id"
            )
            count = db.execute(count_sql, params).scalar() or 0
            updated += count
            print(f"  [check] {table}.{id_column}: {form_type} {old_id!r} -> {new_id!r} ({count} rows would change)")
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the renames.")
    parser.add_argument("--check", action="store_true", help="Report only.")
    args = parser.parse_args()

    if not args.apply and not args.check:
        args.check = True

    if not MAPPINGS:
        print("No mappings declared; nothing to do.")
        return 0

    db = SessionLocal()
    try:
        total = 0
        total += _apply_to_table(db, "questionnaire_answer", "question_id", args.apply)
        total += _apply_to_table(db, "form_filling_field", "questionnaire_item_id", args.apply)
        total += _apply_to_table(db, "form_filling_field", "canonical_questionnaire_id", args.apply)
        if args.apply:
            db.commit()
            print(f"Committed {total} row update(s).")
        else:
            print(f"Dry-run total: {total} row(s) would change.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
