"""Tests for I-192 yes/no checkbox fill from questionnaire answers."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _build_extraction_targets,
    _build_results_from_answers,
    _fix_exclusive_choice_checkbox_results,
    _target_looks_like_exclusive_choice_button,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192YesNoCheckboxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path)).get("fields", [])
        cls.targets = _build_extraction_targets(
            "i-192",
            cls.fields,
            list(map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]),
        )

    def test_yes_no_pdf_widgets_are_exclusive_choice_targets(self) -> None:
        for question_id in ("p2_30", "p2_31", "p2_35", "p2_36"):
            widgets = [
                target
                for target in self.targets
                if target.get("questionnaire_item_id") == question_id
            ]
            self.assertEqual(len(widgets), 2, question_id)
            self.assertTrue(all(_target_looks_like_exclusive_choice_button(t) for t in widgets))

    def test_exclusive_choice_fix_applies_saved_answers(self) -> None:
        answers = {
            "p2_30": "yes",
            "p2_31": "no",
            "p2_35": "no",
            "p2_36": "yes",
        }
        results_by_id: dict[str, dict[str, str]] = {
            target["field_name"]: {"id": target["field_name"], "value": "", "confidence": "low", "justification": ""}
            for target in self.targets
            if target.get("questionnaire_item_id") in answers
        }
        _fix_exclusive_choice_checkbox_results(self.targets, results_by_id, answers)

        def checked(question_id: str, option: str) -> str:
            target = next(
                t
                for t in self.targets
                if t.get("questionnaire_item_id") == question_id
                and t.get("questionnaire_option_value") == option
            )
            return results_by_id[target["field_name"]]["value"]

        self.assertEqual(checked("p2_30", "yes"), "yes")
        self.assertEqual(checked("p2_30", "no"), "off")
        self.assertEqual(checked("p2_31", "yes"), "off")
        self.assertEqual(checked("p2_31", "no"), "yes")
        self.assertEqual(checked("p2_35", "yes"), "off")
        self.assertEqual(checked("p2_35", "no"), "yes")
        self.assertEqual(checked("p2_36", "yes"), "yes")
        self.assertEqual(checked("p2_36", "no"), "off")

    def test_build_results_from_answers_fills_yes_no_pairs(self) -> None:
        answers = {"p2_30": "yes", "p2_36": "no"}
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        def checked(question_id: str, option: str) -> str:
            target = next(
                t
                for t in self.targets
                if t.get("questionnaire_item_id") == question_id
                and t.get("questionnaire_option_value") == option
            )
            return results[target["field_name"]]["value"]

        self.assertEqual(checked("p2_30", "yes"), "yes")
        self.assertEqual(checked("p2_30", "no"), "off")
        self.assertEqual(checked("p2_36", "yes"), "off")
        self.assertEqual(checked("p2_36", "no"), "yes")


if __name__ == "__main__":
    unittest.main()
