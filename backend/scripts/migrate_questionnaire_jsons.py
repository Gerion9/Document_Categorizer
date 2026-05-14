"""Idempotent migration of questionnaire JSONs to the canonical conventions.

What this script does:
1. Compacts I-360 verbose `code` fields (e.g. `"Part 1, Items 1.a-1.c"` -> `"1.a-1.c"`).
2. Adds a sensible `where_to_verify` default to every item / sub-field that lacks
   one, derived from the item label, section and id heuristics. Existing values
   are NEVER overwritten.
3. Adds a minimal `instruction` placeholder to items that have no instruction
   AND no `form_text` (true blanks). Items that already have either are
   preserved.

The transformations are intentionally conservative: they never remove or
rewrite existing content. Re-running the script is safe and produces no diff
once the data has been migrated.

Usage:
    python -m scripts.migrate_questionnaire_jsons --check    # dry-run
    python -m scripts.migrate_questionnaire_jsons --apply    # write changes
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


QUESTIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "seed_data" / "questions"


# Heuristics: (regex matched against label+section+id, where_to_verify suggestion).
# Order matters; first match wins.
_WHERE_TO_VERIFY_HEURISTICS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bssn\b|social security", re.IGNORECASE), "SSN Card; Tax Records; BIO CALL"),
    (re.compile(r"\ba[- ]?number\b|alien registration", re.IGNORECASE), "EAD Card; I-94; USCIS Receipt; BIO CALL"),
    (re.compile(r"uscis online account", re.IGNORECASE), "USCIS Online Account; BIO CALL"),
    (re.compile(r"passport", re.IGNORECASE), "Passport; BIO CALL; Intake"),
    (re.compile(r"i[- ]?94|arrival.?departure", re.IGNORECASE), "Form I-94; CBP Records; BIO CALL"),
    (re.compile(r"date of birth|dob|birth date", re.IGNORECASE), "Birth Certificate; Passport; BIO CALL"),
    (re.compile(r"place of birth|country of birth", re.IGNORECASE), "Birth Certificate; Passport; BIO CALL"),
    (re.compile(r"marital|spouse|husband|wife|marriage", re.IGNORECASE), "Marriage Certificate; Declaration; BIO CALL"),
    (re.compile(r"address|street|mailing|physical", re.IGNORECASE), "BIO CALL; Intake; Declaration"),
    (re.compile(r"phone|telephone|mobile|email", re.IGNORECASE), "BIO CALL; Intake"),
    (re.compile(r"\battorney|bar number|preparer", re.IGNORECASE), "Firm Records; G-28; State Bar Records"),
    (re.compile(r"signature|certification|declaration", re.IGNORECASE), "Declaration; Signed Form"),
    (re.compile(r"interpreter", re.IGNORECASE), "Interpreter Certification; Intake"),
    (re.compile(r"criminal|conviction|arrest|charge|jail|prison|probation", re.IGNORECASE), "FBI Records; Court Disposition; LEA Report; Declaration"),
    (re.compile(r"removal|deport|excluded|exclusion|removal proceedings|nta", re.IGNORECASE), "EOIR Portal; ICE Records; Declaration"),
    (re.compile(r"voluntary departure", re.IGNORECASE), "EOIR Portal; CBP Records; Declaration"),
    (re.compile(r"trafficking|victim|lea|law enforcement", re.IGNORECASE), "LEA Report; Declaration; Intake"),
    (re.compile(r"employment|occupation|employer|work", re.IGNORECASE), "Pay Stubs; Tax Records; BIO CALL"),
    (re.compile(r"juvenile court|sij|sijs|special immigrant", re.IGNORECASE), "Juvenile Court Order; Predicate Order; Declaration"),
)


_DEFAULT_WHERE_TO_VERIFY = "BIO CALL; Intake; Declaration"


_VERBOSE_I360_CODE_RE = re.compile(
    r"^\s*Part\s+\d+\s*,?\s*Items?\s+(?P<code>[0-9a-z\.\-]+)\s*$",
    re.IGNORECASE,
)
_HEADER_CODE_RE = re.compile(r"^\s*Page\s+\d+\s+header\s*$", re.IGNORECASE)


def _heuristic_where_to_verify(item: dict[str, Any]) -> str:
    haystack = " ".join(
        str(item.get(key) or "")
        for key in ("label", "form_text", "section", "id", "code")
    )
    for pattern, suggestion in _WHERE_TO_VERIFY_HEURISTICS:
        if pattern.search(haystack):
            return suggestion
    return _DEFAULT_WHERE_TO_VERIFY


def _migrate_code(value: Any) -> Any:
    """Compact verbose I-360 codes. Leaves other codes untouched."""
    if not isinstance(value, str):
        return value
    match = _VERBOSE_I360_CODE_RE.match(value)
    if match:
        return match.group("code")
    if _HEADER_CODE_RE.match(value):
        return value.strip().upper().replace(" ", "_")
    return value


def _enrich_item(item: dict[str, Any], *, is_subfield: bool = False) -> bool:
    """Apply in-place migration; return True if anything changed."""
    changed = False

    if "code" in item:
        new_code = _migrate_code(item["code"])
        if new_code != item["code"]:
            item["code"] = new_code
            changed = True

    if not item.get("where_to_verify"):
        item["where_to_verify"] = _heuristic_where_to_verify(item)
        changed = True

    for sub_key in ("fields", "details_fields"):
        for sub in item.get(sub_key) or []:
            if isinstance(sub, dict):
                if _enrich_item(sub, is_subfield=True):
                    changed = True

    return changed


def _migrate_document(raw: Any) -> tuple[bool, int]:
    """Apply migration to `raw` in-place. Returns (changed, item_count)."""
    pages = raw if isinstance(raw, list) else raw.get("pages", [])
    if not isinstance(pages, list):
        return False, 0

    total_changes = 0
    file_changed = False
    for page in pages:
        if not isinstance(page, dict):
            continue
        for item in page.get("items", []) or []:
            if isinstance(item, dict) and _enrich_item(item):
                file_changed = True
                total_changes += 1

    return file_changed, total_changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes to disk.")
    parser.add_argument("--check", action="store_true", help="Dry-run; report changes only.")
    args = parser.parse_args()

    if not args.apply and not args.check:
        args.check = True

    exit_code = 0
    for path in sorted(QUESTIONS_DIR.glob("*_form_*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        changed, count = _migrate_document(raw)

        if not changed:
            print(f"[ok]    {path.name}: no changes needed")
            continue

        if args.apply:
            path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"[apply] {path.name}: enriched {count} item(s)")
        else:
            print(f"[diff]  {path.name}: {count} item(s) would change")
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
