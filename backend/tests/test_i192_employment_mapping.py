"""Tests for I-192 employment history PDF field mapping."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192EmploymentMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path)).get("fields", [])
        cls.mapping_by_name = {
            mapping["field_name"]: mapping
            for mapping in map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        }

    def _assert_mapped(self, suffix: str, item_id: str, field_id: str) -> None:
        matches = [
            mapping
            for field_name, mapping in self.mapping_by_name.items()
            if suffix in field_name
        ]
        self.assertTrue(matches, f"No PDF field found containing {suffix!r}")
        for mapping in matches:
            with self.subTest(field_name=mapping["field_name"]):
                self.assertEqual(mapping["questionnaire_item_id"], item_id)
                self.assertEqual(mapping["questionnaire_field_id"], field_id)
                self.assertEqual(mapping["match_score"], 1.0)

    def test_maps_employer_one_fields(self) -> None:
        self._assert_mapped("P2_Line44_EmployerName", "p2_44", "employer_name")
        self._assert_mapped("#subform[5].DateFrom", "p2_44", "employment_from_date")
        self._assert_mapped("#subform[5].DateTo", "p2_44", "employment_to_date")
        self._assert_mapped("#subform[5].Occupation", "p2_44", "occupation")

    def test_maps_employer_two_fields(self) -> None:
        self._assert_mapped("P2_Line45_EmployerName", "p2_45", "employer_name")
        self._assert_mapped("P2_Line45_Occupation", "p2_45", "occupation")
        self._assert_mapped("P2_Line45_DateFrom", "p2_45", "employment_from_date")
        self._assert_mapped("P2_Line45_DateTo", "p2_45", "employment_to_date")


if __name__ == "__main__":
    unittest.main()
