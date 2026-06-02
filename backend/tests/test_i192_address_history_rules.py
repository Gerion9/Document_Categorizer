"""Tests for I-192 address history mapping and name sanitization."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_i192_address_history_answer_rules,
    _build_extraction_targets,
    _build_results_from_answers,
    _propagate_shared_name_to_p2_1,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192AddressHistoryRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path.resolve())).get("fields", [])
        cls.mappings = map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        cls.targets = _build_extraction_targets("i-192", cls.fields, cls.mappings)

    def test_line11_zipcode_maps_to_second_address_row(self) -> None:
        mapping = next(
            item for item in self.mappings if "P2_Line11_ZipCode" in item.get("field_name", "")
        )
        self.assertEqual(mapping["questionnaire_item_id"], "p2_address_history")
        self.assertEqual(mapping["questionnaire_field_id"], "zip_code")

    def test_sanitize_removes_applicant_name_from_address_row(self) -> None:
        answers = {
            "p2_1": {"family_name": "Castrejon", "given_name": "Adrian", "middle_name": ""},
            "p2_address_history": [
                {
                    "street_number_name": "123 Main St",
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": "60601",
                },
                {
                    "street_number_name": "Adrian Castrejon",
                    "city": "Adrian Castrejon",
                    "state": "IL",
                    "zip_code": "60120",
                },
            ],
        }
        result = _apply_i192_address_history_answer_rules(answers)
        self.assertEqual(result["p2_address_history"][1]["street_number_name"], "")
        self.assertEqual(result["p2_address_history"][1]["city"], "")
        self.assertEqual(result["p2_address_history"][1]["zip_code"], "60120")

    def test_pdf_physical_address_2_does_not_repeat_applicant_name(self) -> None:
        answers = {
            "shared.name": {"family_name": "Castrejon", "given_name": "Adrian", "middle_name": ""},
            "p2_address_history": [
                {
                    "street_number_name": "123 Main St",
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": "60601",
                },
                {
                    "street_number_name": "Adrian Castrejon",
                    "city": "Adrian Castrejon",
                    "state": "IL",
                    "zip_code": "60120",
                },
            ],
        }
        answers = _propagate_shared_name_to_p2_1(answers)
        answers = _apply_i192_address_history_answer_rules(answers)
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        def value(suffix: str) -> str:
            target = next(t for t in self.targets if suffix in t.get("field_name", ""))
            return results[target["field_name"]]["value"]

        self.assertEqual(value("P2_Line11_StreetNumberName"), "")
        self.assertEqual(value("P2_Line11_CityOrTown"), "")
        self.assertEqual(value("P2_Line11_State"), "IL")
        self.assertEqual(value("P2_Line11_ZipCode"), "60120")

    def test_physical_address_2_uses_second_row_street_and_city(self) -> None:
        answers = {
            "p2_address_history": [
                {
                    "street_number_name": "123 Main St",
                    "city": "Chicago",
                    "state": "IL",
                    "zip_code": "60601",
                },
                {
                    "street_number_name": "456 Oak Ave",
                    "city": "Elgin",
                    "state": "IL",
                    "zip_code": "60120",
                },
            ],
        }
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        street_target = next(
            t for t in self.targets if "P2_Line11_StreetNumberName" in t.get("field_name", "")
        )
        city_target = next(
            t for t in self.targets if "P2_Line11_CityOrTown" in t.get("field_name", "")
        )
        self.assertEqual(results[street_target["field_name"]]["value"], "456 Oak Ave")
        self.assertEqual(results[city_target["field_name"]]["value"], "Elgin")


if __name__ == "__main__":
    unittest.main()
