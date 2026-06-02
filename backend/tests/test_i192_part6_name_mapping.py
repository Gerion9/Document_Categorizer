"""Tests for I-192 Part 6 applicant name header mapping and fill."""

from __future__ import annotations

import unittest
from pathlib import Path

from app.services.form_filling_service import (
    _build_extraction_targets,
    _build_results_from_answers,
    _propagate_applicant_name_to_p6_header,
    _propagate_shared_name_to_p2_1,
)
from app.services.form_type_matcher import map_pdf_fields_to_questionnaire_ids
from app.services.pdf_form_service import detect_form_fields


class I192Part6NameMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pdf_path = Path(__file__).resolve().parents[1] / "app" / "seed_data" / "forms" / "i-192.pdf"
        cls.fields = detect_form_fields(str(pdf_path)).get("fields", [])
        cls.mapping_by_name = {
            mapping["field_name"]: mapping
            for mapping in map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]
        }
        cls.targets = _build_extraction_targets(
            "i-192",
            cls.fields,
            list(map_pdf_fields_to_questionnaire_ids("i-192", cls.fields)["mappings"]),
        )

    def test_part6_name_fields_map_to_p6_header(self) -> None:
        expected = {
            "P2_Line1_FamilyName[1]": ("p6_header", "part6_family_name"),
            "P2_Line1_GivenName[1]": ("p6_header", "part6_given_name"),
            "P2_Line1_MiddleName[1]": ("p6_header", "part6_middle_name"),
        }
        for suffix, (item_id, field_id) in expected.items():
            matches = [
                mapping
                for field_name, mapping in self.mapping_by_name.items()
                if suffix in field_name
            ]
            self.assertEqual(len(matches), 1, suffix)
            mapping = matches[0]
            self.assertEqual(mapping["questionnaire_item_id"], item_id)
            self.assertEqual(mapping["questionnaire_field_id"], field_id)

    def test_part6_name_fields_fill_from_shared_name(self) -> None:
        answers = _propagate_applicant_name_to_p6_header(
            _propagate_shared_name_to_p2_1(
                {
                    "shared.name": {
                        "family_name": "Garcia",
                        "given_name": "Maria",
                        "middle_name": "Lopez",
                    }
                }
            )
        )
        results = _build_results_from_answers(self.targets, answers, pdf_fields=self.fields)
        part6_targets = [
            target
            for target in self.targets
            if "subform[8]" in target.get("field_name", "")
            and "Line1_" in target.get("field_name", "")
        ]
        values = {
            target["questionnaire_field_id"]: results[target["field_name"]]["value"]
            for target in part6_targets
            if target.get("questionnaire_field_id")
        }
        self.assertEqual(
            values,
            {
                "part6_family_name": "Garcia",
                "part6_given_name": "Maria",
                "part6_middle_name": "Lopez",
            },
        )


if __name__ == "__main__":
    unittest.main()
