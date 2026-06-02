"""Tests for I-192 travel info item 42 length-of-stay handling."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_i192_skipped_travel_info_answer_rules,
    _build_extraction_targets,
    _build_results_from_answers,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192TravelInfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path.resolve())).get("fields", [])
        cls.targets = _build_extraction_targets(
            "i-192",
            cls.fields,
            list(map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]),
        )
        cls.line42_target = next(
            target for target in cls.targets if "P2_Line42_" in target.get("field_name", "")
        )

    def test_line42_maps_to_approximate_length_of_stay(self) -> None:
        self.assertEqual(self.line42_target["questionnaire_item_id"], "p2_travel_info")
        self.assertEqual(
            self.line42_target["questionnaire_field_id"],
            "approximate_length_of_stay",
        )

    def test_birth_country_does_not_fill_length_of_stay(self) -> None:
        answers = _apply_i192_skipped_travel_info_answer_rules(
            {"shared.biographics": {"birth_country": "Mexico"}}
        )
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)
        self.assertEqual(results[self.line42_target["field_name"]]["value"], "")

    def test_valid_length_of_stay_is_preserved(self) -> None:
        answers = {
            "p2_travel_info": {
                "intended_entry_city": "",
                "intended_entry_state": "",
                "name_of_port_of_entry": "",
                "travel_method": "",
                "planned_entry_date": "",
                "approximate_length_of_stay": "6 months",
                "purpose_of_stay": "",
            }
        }
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)
        self.assertEqual(results[self.line42_target["field_name"]]["value"], "6 months")


if __name__ == "__main__":
    unittest.main()
