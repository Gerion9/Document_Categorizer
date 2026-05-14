"""End-to-end pipeline mapping snapshot tests, one per supported form.

For every form in the registry we:
1. Detect AcroForm fields with PyMuPDF.
2. Map them against the canonical questionnaire definitions.

We then assert the matched count and the canonical questionnaire ids that the
mapper produced. The expected values are stored as JSON snapshots under
`tests/golden/pipeline/`. Regenerate with:

    UPDATE_GOLDEN=1 python -m pytest tests/test_form_filling_pipeline_golden.py
"""

import json
import os
import unittest
from pathlib import Path

from app.services import form_registry
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


_GOLDEN_DIR = Path(__file__).parent / "golden" / "pipeline"


def _golden_path(form_type: str) -> Path:
    return _GOLDEN_DIR / f"{form_type}.json"


class FormFillingPipelineGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        _GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        self.update_golden = os.environ.get("UPDATE_GOLDEN") == "1"

    def _build_summary(self, form_type: str) -> dict:
        spec = form_registry.get_form_spec(form_type)
        pdf_path = spec.pdf_path()
        if not pdf_path.exists():
            self.skipTest(f"PDF missing for {form_type}: {pdf_path}")
        detection = detect_form_fields(pdf_path)
        pdf_fields = detection.get("fields", []) or []
        mapping = map_pdf_fields_to_questionnaire_ids(form_type, pdf_fields)
        item_ids = sorted({
            entry.get("questionnaire_item_id")
            for entry in mapping.get("mappings", [])
            if entry.get("questionnaire_item_id")
        })
        return {
            "form_type": form_type,
            "field_count": int(mapping.get("field_count") or 0),
            "matched_count": int(mapping.get("matched_count") or 0),
            "expected_item_count": int(mapping.get("expected_item_count") or 0),
            "matched_item_count": int(mapping.get("matched_item_count") or 0),
            "low_coverage_warning": bool(mapping.get("low_coverage_warning")),
            "matched_item_ids": item_ids,
        }

    def _assert_snapshot(self, form_type: str, summary: dict) -> None:
        path = _golden_path(form_type)
        rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
        if self.update_golden or not path.exists():
            path.write_text(rendered, encoding="utf-8")
            self.skipTest(f"Updated golden snapshot: {path}")
            return
        expected = path.read_text(encoding="utf-8")
        self.assertEqual(
            expected,
            rendered,
            f"Pipeline mapping changed for {form_type}. "
            "Run UPDATE_GOLDEN=1 pytest tests/test_form_filling_pipeline_golden.py to refresh.",
        )

    def test_pipeline_mapping_snapshot_per_form(self) -> None:
        for form_type in form_registry.FORM_REGISTRY:
            with self.subTest(form_type=form_type):
                try:
                    summary = self._build_summary(form_type)
                except unittest.SkipTest:
                    raise
                except Exception as exc:  # pragma: no cover - defensive
                    self.fail(f"Pipeline failed for {form_type}: {exc}")
                self._assert_snapshot(form_type, summary)


if __name__ == "__main__":
    unittest.main()
