"""Tests for I-192 other-names answer cleanup and PDF fill."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _apply_i192_other_names_answer_rules,
    _build_extraction_targets,
    _build_results_from_answers,
    _postprocess_i192_other_names_pdf_values,
    _propagate_shared_name_to_p2_1,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192OtherNamesRulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path.resolve())).get("fields", [])
        cls.mappings = map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        cls.targets = _build_extraction_targets("i-192", cls.fields, cls.mappings)

    def test_line2_fields_map_to_other_names(self) -> None:
        row_a_family = next(
            item for item in self.mappings if "P2_Line2_A_FamilyName" in item.get("field_name", "")
        )
        row_a_given = next(
            item for item in self.mappings if "P2_Line2_A_FirstName" in item.get("field_name", "")
        )
        self.assertEqual(row_a_family["questionnaire_item_id"], "p2_2")
        self.assertEqual(row_a_family["questionnaire_field_id"], "other_family_name")
        self.assertEqual(row_a_given["questionnaire_item_id"], "p2_2")
        self.assertEqual(row_a_given["questionnaire_field_id"], "other_given_name")

    def test_pdf_other_names_do_not_repeat_legal_given_name(self) -> None:
        answers = {
            "shared.name": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "Lopez",
            },
            "p2_2": {
                "other_family_name": "Garcia",
                "other_given_name": "Maria",
                "other_middle_name": "Lopez",
            },
        }
        answers = _propagate_shared_name_to_p2_1(answers)
        answers = _apply_i192_other_names_answer_rules(answers)
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)

        row_a_family = next(
            target for target in self.targets if "P2_Line2_A_FamilyName" in target.get("field_name", "")
        )
        row_a_given = next(
            target for target in self.targets if "P2_Line2_A_FirstName" in target.get("field_name", "")
        )
        self.assertEqual(results[row_a_family["field_name"]]["value"], "")
        self.assertEqual(results[row_a_given["field_name"]]["value"], "")

    def test_postprocess_clears_leaked_legal_given_name(self) -> None:
        results_by_id = {
            "FormI-192[0].#subform[1].P2_Line2_A_FamilyName[0]": {
                "id": "FormI-192[0].#subform[1].P2_Line2_A_FamilyName[0]",
                "value": "",
                "confidence": "low",
                "justification": "",
            },
            "FormI-192[0].#subform[1].P2_Line2_A_FirstName[0]": {
                "id": "FormI-192[0].#subform[1].P2_Line2_A_FirstName[0]",
                "value": "Maria",
                "confidence": "high",
                "justification": "Saved questionnaire answer from shared.name.given_name.",
            },
        }
        answers = {
            "p2_1": {"family_name": "Garcia", "given_name": "Maria", "middle_name": ""},
        }
        touched = _postprocess_i192_other_names_pdf_values(results_by_id, answers)
        self.assertIn("FormI-192[0].#subform[1].P2_Line2_A_FirstName[0]", touched)
        self.assertEqual(
            results_by_id["FormI-192[0].#subform[1].P2_Line2_A_FirstName[0]"]["value"],
            "",
        )

    def test_clears_p2_2_when_it_matches_legal_name(self) -> None:
        answers = {
            "p2_1": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "Lopez",
            },
            "p2_2": {
                "other_family_name": "Garcia",
                "other_given_name": "Maria",
                "other_middle_name": "Lopez",
            },
        }

        result = _apply_i192_other_names_answer_rules(answers)

        self.assertEqual(
            result["p2_2"],
            {
                "other_family_name": "",
                "other_given_name": "",
                "other_middle_name": "",
            },
        )

    def test_keeps_p2_2_when_name_differs_from_legal_name(self) -> None:
        answers = {
            "p2_1": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "",
            },
            "p2_2": {
                "other_family_name": "Smith",
                "other_given_name": "Mary",
                "other_middle_name": "",
            },
        }

        result = _apply_i192_other_names_answer_rules(answers)

        self.assertEqual(result["p2_2"], answers["p2_2"])

    def test_filters_duplicate_rows_from_shared_other_names_used(self) -> None:
        answers = {
            "shared.name": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "",
            },
            "shared.other_names_used": [
                {
                    "family_name": "Garcia",
                    "given_name": "Maria",
                    "middle_name": "",
                },
                {
                    "family_name": "Smith",
                    "given_name": "Mary",
                    "middle_name": "",
                },
            ],
        }

        result = _apply_i192_other_names_answer_rules(answers)

        self.assertEqual(
            result["shared.other_names_used"],
            [
                {
                    "family_name": "Smith",
                    "given_name": "Mary",
                    "middle_name": "",
                }
            ],
        )

    def test_name_comparison_is_case_insensitive(self) -> None:
        answers = {
            "p2_1": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "",
            },
            "p2_2": {
                "other_family_name": "GARCIA",
                "other_given_name": "maria",
                "other_middle_name": "",
            },
        }

        result = _apply_i192_other_names_answer_rules(answers)

        self.assertEqual(result["p2_2"]["other_family_name"], "")

    def test_name_comparison_is_accent_insensitive(self) -> None:
        answers = {
            "p2_1": {
                "family_name": "Garcia",
                "given_name": "Maria",
                "middle_name": "",
            },
            "p2_2": {
                "other_family_name": "García",
                "other_given_name": "María",
                "other_middle_name": "",
            },
        }

        result = _apply_i192_other_names_answer_rules(answers)

        self.assertEqual(result["p2_2"]["other_family_name"], "")


if __name__ == "__main__":
    unittest.main()
