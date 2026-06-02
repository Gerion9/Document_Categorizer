"""Tests for I-192 Sex checkbox mapping and fill."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _build_extraction_targets,
    _build_results_from_answers,
    _target_looks_like_exclusive_choice_button,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192SexCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path.resolve())).get("fields", [])
        cls.mappings = map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        cls.targets = _build_extraction_targets("i-192", cls.fields, cls.mappings)

    def test_sex_widgets_map_to_p2_8_options(self) -> None:
        male = next(item for item in self.mappings if "P2_Line8_Sex[0]" in item.get("field_name", ""))
        female = next(item for item in self.mappings if "P2_Line8_Sex[1]" in item.get("field_name", ""))
        self.assertEqual(male["questionnaire_item_id"], "p2_8")
        self.assertEqual(male["questionnaire_option_value"], "Male")
        self.assertEqual(female["questionnaire_item_id"], "p2_8")
        self.assertEqual(female["questionnaire_option_value"], "Female")

    def test_sex_widgets_are_exclusive_choice_targets(self) -> None:
        widgets = [
            target for target in self.targets if target.get("questionnaire_item_id") == "p2_8"
        ]
        self.assertEqual(len(widgets), 2)
        self.assertTrue(all(_target_looks_like_exclusive_choice_button(widget) for widget in widgets))

    def test_build_results_marks_male_from_saved_answer(self) -> None:
        answers = {"p2_8": "Male", "shared.biographics": {"sex": "Male"}}
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        male_target = next(
            target
            for target in self.targets
            if target.get("questionnaire_item_id") == "p2_8"
            and target.get("questionnaire_option_value") == "Male"
        )
        female_target = next(
            target
            for target in self.targets
            if target.get("questionnaire_item_id") == "p2_8"
            and target.get("questionnaire_option_value") == "Female"
        )
        self.assertEqual(results[male_target["field_name"]]["value"], "yes")
        self.assertEqual(results[female_target["field_name"]]["value"], "off")

    def test_build_results_marks_female_from_shared_biographics(self) -> None:
        answers = {"shared.biographics": {"sex": "Female"}}
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        male_target = next(
            target
            for target in self.targets
            if target.get("questionnaire_option_value") == "Male"
        )
        female_target = next(
            target
            for target in self.targets
            if target.get("questionnaire_option_value") == "Female"
        )
        self.assertEqual(results[male_target["field_name"]]["value"], "off")
        self.assertEqual(results[female_target["field_name"]]["value"], "yes")


if __name__ == "__main__":
    unittest.main()
