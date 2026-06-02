"""Tests for I-192 G-28 attached checkbox mapping and fill."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_questionnaire_defaults_to_answers,
    _build_extraction_targets,
    _build_results_from_answers,
    _postprocess_i192_default_pdf_values,
    _questionnaire_pages_for_form_defaults,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192G28AttachedCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path)).get("fields", [])
        cls.mappings = map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        cls.targets = _build_extraction_targets("i-192", cls.fields, cls.mappings)

    def test_g28_checkbox_maps_to_global_attorney_info(self) -> None:
        mapping = next(
            item
            for item in self.mappings
            if "CheckBox2" in item.get("field_name", "")
        )
        self.assertEqual(mapping["questionnaire_item_id"], "p_global_attorney_info")
        self.assertEqual(mapping["questionnaire_field_id"], "g28_attached")
        self.assertEqual(mapping["match_score"], 1.0)

    def test_default_answers_check_g28_attached_box(self) -> None:
        pages = _questionnaire_pages_for_form_defaults("i-192")
        answers = _apply_questionnaire_defaults_to_answers(pages, {})
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)
        checkbox_target = next(
            target for target in self.targets if "CheckBox2" in target.get("field_name", "")
        )
        self.assertEqual(results[checkbox_target["field_name"]]["value"], "yes")

    def test_postprocess_uses_shared_attorney_answer(self) -> None:
        results_by_id = {
            target["field_name"]: {
                "id": target["field_name"],
                "value": "",
                "confidence": "low",
                "justification": "",
            }
            for target in self.targets
            if "CheckBox2" in target.get("field_name", "")
        }
        answers = {"shared_attorney.info": {"g28_attached": True}}
        _postprocess_i192_default_pdf_values(results_by_id, answers)
        field_name = next(name for name in results_by_id if "CheckBox2" in name)
        self.assertEqual(results_by_id[field_name]["value"], "yes")


if __name__ == "__main__":
    unittest.main()
