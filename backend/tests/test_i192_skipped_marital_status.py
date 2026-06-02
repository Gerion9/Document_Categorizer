"""Tests for I-192 skipped marital status (item 2.12)."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_i192_skipped_marital_history_answer_rules,
    _apply_questionnaire_defaults_to_answers,
    _build_extraction_targets,
    _build_results_from_answers,
    _questionnaire_pages_for_form_defaults,
    _resolve_forced_questionnaire_answer,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192SkippedMaritalStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path.resolve())).get("fields", [])
        cls.targets = _build_extraction_targets(
            "i-192",
            cls.fields,
            list(map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]),
        )
        cls.marital_target = next(
            target for target in cls.targets if target.get("questionnaire_item_id") == "p2_12"
        )

    def test_forced_default_applies_blank_when_answer_missing(self) -> None:
        resolution = _resolve_forced_questionnaire_answer(
            self.marital_target,
            {"shared.biographics": {"marital_status": "Single, Never Married"}},
        )
        self.assertEqual(resolution, ("", "p2_12"))

    def test_skipped_rules_clear_autofilled_marital_status(self) -> None:
        answers = _apply_i192_skipped_marital_history_answer_rules(
            {
                "p2_12": "Married",
                "p2_13": "2",
                "shared.biographics": {"marital_status": "Married"},
            }
        )
        self.assertEqual(answers["p2_12"], "")
        self.assertEqual(answers["p2_13"], "")

    def test_defaults_keep_p2_12_blank_even_with_shared_marital_status(self) -> None:
        pages = _questionnaire_pages_for_form_defaults("i-192")
        answers = _apply_questionnaire_defaults_to_answers(
            pages,
            {"shared.biographics": {"marital_status": "Single, Never Married"}},
        )
        answers = _apply_i192_skipped_marital_history_answer_rules(answers)
        self.assertEqual(answers.get("p2_12"), "")

    def test_pdf_leaves_marital_status_unchecked_when_only_shared_value_exists(self) -> None:
        answers = {"shared.biographics": {"marital_status": "Single, Never Married"}}
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        checked = [
            target.get("questionnaire_option_value")
            for target in self.targets
            if target.get("questionnaire_item_id") == "p2_12"
            and results[target["field_name"]]["value"] == "yes"
        ]
        self.assertEqual(checked, [])


if __name__ == "__main__":
    unittest.main()
