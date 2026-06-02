"""Tests for I-192 attorney USCIS Online Account Number mapping and fill."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_questionnaire_defaults_to_answers,
    _build_extraction_targets,
    _build_results_from_answers,
    _questionnaire_pages_for_form_defaults,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192AttorneyUscisAccountMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path)).get("fields", [])
        cls.mappings = map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        cls.targets = _build_extraction_targets("i-192", cls.fields, cls.mappings)

    def test_attorney_uscis_account_maps_to_global_attorney_info(self) -> None:
        mapping = next(
            item
            for item in self.mappings
            if "#subform[0].USCISOnlineAcctNumber" in item.get("field_name", "")
        )
        self.assertEqual(mapping["questionnaire_item_id"], "p_global_attorney_info")
        self.assertEqual(mapping["questionnaire_field_id"], "attorney_uscis_online_account_number")
        self.assertEqual(mapping["match_score"], 1.0)

    def test_client_uscis_account_still_maps_to_p2_4(self) -> None:
        mapping = next(
            item
            for item in self.mappings
            if "P2_Line4_USCISOnlineAcctNumber" in item.get("field_name", "")
        )
        self.assertEqual(mapping["questionnaire_item_id"], "p2_4")
        self.assertIsNone(mapping["questionnaire_field_id"])

    def test_default_answers_fill_attorney_uscis_account(self) -> None:
        pages = _questionnaire_pages_for_form_defaults("i-192")
        answers = _apply_questionnaire_defaults_to_answers(pages, {})
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)
        attorney_target = next(
            target
            for target in self.targets
            if "#subform[0].USCISOnlineAcctNumber" in target.get("field_name", "")
        )
        self.assertEqual(results[attorney_target["field_name"]]["value"], "087361245002")


if __name__ == "__main__":
    unittest.main()
