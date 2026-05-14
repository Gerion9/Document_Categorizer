"""Snapshot tests for form-filling prompts.

We do not assert exact prompt contents (those will evolve); instead we keep a
golden snapshot per form so reviewers can see when a prompt changes. The
snapshot lives under `tests/golden/prompts/`. Regenerate with:

    UPDATE_GOLDEN=1 python -m pytest tests/test_prompt_snapshots.py

When `UPDATE_GOLDEN` is unset, the test asserts equality with the committed
snapshot.
"""

import os
import unittest
from pathlib import Path

from app.prompts.form_filling_prompts import (
    build_batch_system_prompt,
    build_field_extraction_system_prompt,
)
from app.services import form_registry


_GOLDEN_DIR = Path(__file__).parent / "golden" / "prompts"


def _golden_path(form_type: str, kind: str) -> Path:
    return _GOLDEN_DIR / f"{form_type}.{kind}.golden.txt"


class PromptSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        self.update_golden = os.environ.get("UPDATE_GOLDEN") == "1"

    def _assert_snapshot(self, form_type: str, kind: str, rendered: str) -> None:
        path = _golden_path(form_type, kind)
        if self.update_golden or not path.exists():
            path.write_text(rendered, encoding="utf-8")
            self.skipTest(f"Updated golden snapshot: {path}")
            return
        expected = path.read_text(encoding="utf-8")
        self.assertEqual(
            expected,
            rendered,
            f"Prompt snapshot drifted for {form_type}.{kind}. "
            f"Run UPDATE_GOLDEN=1 pytest tests/test_prompt_snapshots.py to refresh.",
        )

    def test_single_prompt_snapshots(self) -> None:
        for form_type in form_registry.FORM_REGISTRY:
            with self.subTest(form_type=form_type, kind="single"):
                rendered = build_field_extraction_system_prompt(form_type)
                self._assert_snapshot(form_type, "single", rendered)

    def test_batch_prompt_snapshots(self) -> None:
        for form_type in form_registry.FORM_REGISTRY:
            with self.subTest(form_type=form_type, kind="batch"):
                rendered = build_batch_system_prompt(form_type)
                self._assert_snapshot(form_type, "batch", rendered)


if __name__ == "__main__":
    unittest.main()
