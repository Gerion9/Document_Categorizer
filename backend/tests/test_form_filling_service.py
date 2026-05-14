import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services import form_filling_service as service


class _FakeQuery:
    def __init__(self, existing_page=None) -> None:
        self._existing_page = existing_page

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._existing_page


class _FakeDb:
    def __init__(self, existing_page=None) -> None:
        self._existing_page = existing_page
        self.added = []
        self.commit_calls = 0

    def query(self, model):
        if model is service.Page:
            return _FakeQuery(self._existing_page)
        return _FakeQuery()

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commit_calls += 1


def _minimal_autofill_target(field_id: str) -> dict:
    return {
        "id": field_id,
        "field_name": field_id,
        "field_label": field_id,
        "field_type": "text",
        "page_number": 1,
        "canonical_questionnaire_id": field_id,
        "questionnaire_item_id": field_id,
        "questionnaire_field_id": None,
        "question_id": field_id,
        "answer_field_id": None,
        "questionnaire_item_type": "text",
        "questionnaire_options": [],
    }


class FormFillingServiceTests(unittest.TestCase):
    def test_build_generated_form_filename_uses_shared_name_answers(self) -> None:
        job = SimpleNamespace(
            id="job-12345678",
            case_id="case-1",
            form_type="i-914",
        )

        with patch.object(
            service,
            "get_questionnaire_answers",
            return_value={
                "shared.name": {
                    "given_name": "Marisol",
                    "middle_name": "Elena",
                    "family_name": "Ramirez",
                }
            },
        ):
            filename = service.build_generated_form_filename(SimpleNamespace(), job)
            safe_filename = service.build_generated_form_filename(
                SimpleNamespace(),
                job,
                safe=True,
            )

        self.assertEqual(filename, "I-914_Marisol Elena Ramirez.pdf")
        self.assertEqual(safe_filename, "I-914_Marisol_Elena_Ramirez.pdf")

    def test_import_generated_pdf_pages_creates_case_pages_for_new_job(self) -> None:
        db = _FakeDb()
        job = SimpleNamespace(
            id="job-12345678",
            case_id="case-1",
            form_type="i-130",
            filled_pdf_path="exports/i130_filled.pdf",
        )

        with (
            patch.object(
                service,
                "build_generated_form_filename",
                return_value="I-130_Marisol Elena Ramirez.pdf",
            ),
            patch.object(service, "_resolve_generated_pdf_upload_key", return_value="uploads/generated.pdf"),
            patch.object(
                service,
                "split_pdf",
                return_value=[
                    {
                        "page_number": 1,
                        "file_path": "pages/generated-1.jpg",
                        "thumbnail_path": "thumbnails/generated-1.jpg",
                    },
                    {
                        "page_number": 2,
                        "file_path": "pages/generated-2.jpg",
                        "thumbnail_path": "thumbnails/generated-2.jpg",
                    },
                ],
            ),
            patch.object(service, "get_s3_service", return_value=SimpleNamespace()),
        ):
            created_count = service._import_generated_pdf_pages(db, job)

        pages = [obj for obj in db.added if isinstance(obj, service.Page)]
        audits = [obj for obj in db.added if isinstance(obj, service.AuditLog)]

        self.assertEqual(created_count, 2)
        self.assertEqual(len(pages), 2)
        self.assertEqual(len(audits), 1)
        self.assertEqual(pages[0].case_id, "case-1")
        self.assertEqual(pages[0].source_document_id, "form-filling-job:job-12345678")
        self.assertEqual(pages[0].original_filename, "I-130_Marisol Elena Ramirez.pdf")
        self.assertEqual(pages[0].status, service.PageStatus.UNCLASSIFIED.value)
        self.assertEqual(pages[0].metadata_json["source"], "form_filling")
        self.assertEqual(pages[0].metadata_json["form_filling_job_id"], "job-12345678")
        self.assertEqual(db.commit_calls, 1)

    def test_import_generated_pdf_pages_skips_existing_generated_document(self) -> None:
        db = _FakeDb(existing_page=SimpleNamespace(id="page-1"))
        job = SimpleNamespace(
            id="job-12345678",
            case_id="case-1",
            form_type="i-130",
            filled_pdf_path="exports/i130_filled.pdf",
        )

        with (
            patch.object(service, "_resolve_generated_pdf_upload_key") as resolve_mock,
            patch.object(service, "split_pdf") as split_mock,
        ):
            created_count = service._import_generated_pdf_pages(db, job)

        self.assertEqual(created_count, 0)
        self.assertEqual(db.added, [])
        self.assertEqual(db.commit_calls, 0)
        resolve_mock.assert_not_called()
        split_mock.assert_not_called()

    def test_build_extraction_targets_propagates_qc_hints(self) -> None:
        pdf_fields = [
            {
                "field_name": "field_1",
                "field_label": "Date of Birth",
                "field_type": "date",
                "field_type_hint": "text",
                "page_number": 2,
                "nearby_text": "Date of Birth",
                "button_values": [],
                "choice_values": [],
            }
        ]
        mappings = [
            {
                "field_name": "field_1",
                "questionnaire_item_id": "p2_10",
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": "p2_10",
                "confidence": "medium",
                "matched_label": "Date of Birth",
                "matched_section": "Part 2. General Information About You (continued)",
                "matched_responsible_party": "client",
                "source_file": "test.json",
                "match_score": 0.51,
            }
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "p2_10",
                "item_id": "p2_10",
                "field_id": None,
                "label": "Date of Birth",
                "form_text": "Date of Birth",
                "section": "Part 2. General Information About You (continued)",
                "responsible_party": "client",
                "item_type": "date",
                "source_file": "test.json",
                "qc_description": "Is the applicant's date of birth correct?",
                "qc_where_to_verify": "Birth Cert / Passport",
            }
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target["questionnaire_where_to_verify"], "Birth Cert / Passport")
        self.assertIn("Is the applicant's date of birth correct?", target["search_query"])
        self.assertIn("Birth Cert / Passport", target["search_query"])

    def test_build_shared_autofill_targets_marks_default_fields(self) -> None:
        pages = [
            {
                "page": 1,
                "items": [
                    {
                        "id": "shared.safe_mailing",
                        "responsible_party": "client",
                        "type": "group",
                        "form_text": "Safe mailing address",
                        "fields": [
                            {
                                "id": "country",
                                "label": "Country",
                                "type": "text",
                                "default_value": "United States",
                                "force_default": True,
                            }
                        ],
                    }
                ],
            }
        ]

        targets = service._build_shared_autofill_targets(pages)

        self.assertEqual(targets[0]["questionnaire_default_value"], "United States")
        self.assertTrue(targets[0]["questionnaire_force_default"])

    def test_build_extraction_targets_propagates_default_metadata(self) -> None:
        pdf_fields = [
            {
                "field_name": "field_1",
                "field_label": "Country",
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 1,
                "nearby_text": "Country",
                "button_values": [],
                "choice_values": [],
            }
        ]
        mappings = [
            {
                "field_name": "field_1",
                "questionnaire_item_id": "mailing",
                "questionnaire_field_id": "country",
                "canonical_questionnaire_id": "mailing.country",
                "confidence": "medium",
            }
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "mailing.country",
                "item_id": "mailing",
                "field_id": "country",
                "label": "Country",
                "form_text": "Mailing address",
                "section": "Part 1",
                "responsible_party": "client",
                "item_type": "text",
                "default_value": "United States",
                "force_default": True,
            }
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        self.assertEqual(targets[0]["questionnaire_default_value"], "United States")
        self.assertTrue(targets[0]["questionnaire_force_default"])

    def test_build_extraction_targets_fallback_maps_unmatched_yes_no_fields_by_label(self) -> None:
        pdf_fields = [
            {
                "field_name": "form1[0].#subform[7].Dq5a_no[0]",
                "field_label": (
                    "PART 4. Processing Information. 4. Have you EVER been a member of, "
                    "solicited money or members for, provided support for, attended military "
                    "training by or on behalf of, or been associated with an organization that is: "
                    "A. Designated as a terrorist organization under the Immigration and Nationality "
                    "Act section 219? Select No."
                ),
                "field_type": "checkbox",
                "field_type_hint": "button",
                "page_number": 5,
                "nearby_text": (
                    "Yes | No | Designated as a terrorist organization under the Immigration and "
                    "Nationality Act section 219?"
                ),
                "button_values": ["1"],
                "choice_values": [],
            },
            {
                "field_name": "form1[0].#subform[7].Dq5a_yes[0]",
                "field_label": (
                    "PART 4. Processing Information. 4. Have you EVER been a member of, "
                    "solicited money or members for, provided support for, attended military "
                    "training by or on behalf of, or been associated with an organization that is: "
                    "A. Designated as a terrorist organization under the Immigration and Nationality "
                    "Act section 219? Select Yes."
                ),
                "field_type": "checkbox",
                "field_type_hint": "button",
                "page_number": 5,
                "nearby_text": (
                    "Yes | Designated as a terrorist organization under the Immigration and "
                    "Nationality Act section 219? | No"
                ),
                "button_values": ["1"],
                "choice_values": [],
            },
        ]
        mappings = [
            {
                "field_name": pdf_fields[0]["field_name"],
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": pdf_fields[1]["field_name"],
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "p4_4a",
                "item_id": "p4_4a",
                "item_code": "4.4.A",
                "item_type": "yes_no",
                "page_number": 5,
                "label": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "form_text": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "section": "Part 4. Processing Information (continued)",
                "responsible_party": "client",
                "field_id": None,
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
            {
                "canonical_questionnaire_id": "p4_4a",
                "item_id": "p4_4a",
                "item_code": "4.4.A",
                "item_type": "yes_no",
                "page_number": 5,
                "label": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "form_text": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "section": "Part 4. Processing Information (continued)",
                "responsible_party": "client",
                "field_id": None,
                "option_value": "yes",
                "option_label": "Yes",
                "source_file": "i914_form_client.json",
            },
            {
                "canonical_questionnaire_id": "p4_4a",
                "item_id": "p4_4a",
                "item_code": "4.4.A",
                "item_type": "yes_no",
                "page_number": 5,
                "label": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "form_text": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                "section": "Part 4. Processing Information (continued)",
                "responsible_party": "client",
                "field_id": None,
                "option_value": "no",
                "option_label": "No",
                "source_file": "i914_form_client.json",
            },
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        by_field_name = {target["field_name"]: target for target in targets}
        no_target = by_field_name["form1[0].#subform[7].Dq5a_no[0]"]
        yes_target = by_field_name["form1[0].#subform[7].Dq5a_yes[0]"]

        self.assertEqual(no_target["canonical_questionnaire_id"], "p4_4a")
        self.assertEqual(yes_target["canonical_questionnaire_id"], "p4_4a")
        self.assertEqual(no_target["questionnaire_item_id"], "p4_4a")
        self.assertEqual(yes_target["questionnaire_item_id"], "p4_4a")
        self.assertEqual(no_target["questionnaire_option_value"], "no")
        self.assertEqual(yes_target["questionnaire_option_value"], "yes")

    def test_build_results_from_answers_uses_fallback_mapped_yes_no_targets(self) -> None:
        targets = [
            {
                "field_name": "form1[0].#subform[7].Dq5a_no[0]",
                "canonical_questionnaire_id": "p4_4a",
                "questionnaire_item_id": "p4_4a",
                "questionnaire_field_id": None,
                "questionnaire_item_type": "yes_no",
                "questionnaire_option_value": "no",
                "questionnaire_option_label": "No",
                "questionnaire_options": [
                    {"value": "yes", "label": "Yes"},
                    {"value": "no", "label": "No"},
                ],
                "field_type": "checkbox",
                "field_label": "Designated as a terrorist organization under the Immigration and Nationality Act section 219? Select No.",
            },
            {
                "field_name": "form1[0].#subform[7].Dq5a_yes[0]",
                "canonical_questionnaire_id": "p4_4a",
                "questionnaire_item_id": "p4_4a",
                "questionnaire_field_id": None,
                "questionnaire_item_type": "yes_no",
                "questionnaire_option_value": "yes",
                "questionnaire_option_label": "Yes",
                "questionnaire_options": [
                    {"value": "yes", "label": "Yes"},
                    {"value": "no", "label": "No"},
                ],
                "field_type": "checkbox",
                "field_label": "Designated as a terrorist organization under the Immigration and Nationality Act section 219? Select Yes.",
            },
        ]

        results = service._build_results_from_answers(targets, {"p4_4a": "no"})

        self.assertEqual(results["form1[0].#subform[7].Dq5a_no[0]"]["value"], "yes")
        self.assertEqual(results["form1[0].#subform[7].Dq5a_yes[0]"]["value"], "off")

    def test_build_results_from_answers_skips_pdf417_barcode_fields(self) -> None:
        targets = [
            {
                "field_name": "form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]",
                "id": "form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]",
                "canonical_questionnaire_id": "p_attorney_info.attorney_uscis_online_account_number",
                "questionnaire_item_id": "p_attorney_info",
                "questionnaire_field_id": "attorney_uscis_online_account_number",
                "field_type": "text",
                "field_label": "PDF417BarCode1",
            }
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "p_attorney_info": {
                    "attorney_uscis_online_account_number": "087361245002",
                }
            },
        )

        self.assertEqual(
            results["form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]"]["value"],
            "",
        )
        self.assertIn(
            "generated page artifact",
            results["form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]"]["justification"].lower(),
        )

    def test_build_pdf_value_map_skips_pdf417_barcode_fields(self) -> None:
        field_rows = [
            SimpleNamespace(
                field_name="form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]",
                field_label="PDF417BarCode1",
                field_type="text",
                extracted_value="087361245002",
            ),
            SimpleNamespace(
                field_name="form1[0].#subform[0].TextField1[1]",
                field_label="Attorney USCIS Online Account Number",
                field_type="text",
                extracted_value="087361245002",
            ),
        ]

        value_map = service._build_pdf_value_map(field_rows)

        self.assertNotIn("form1[0].#pageSet[0].Page1[0].PDF417BarCode1[0]", value_map)
        self.assertEqual(value_map["form1[0].#subform[0].TextField1[1]"], "087361245002")

    def test_build_results_from_answers_skips_lea_unit_number_by_field_id(self) -> None:
        targets = [
            {
                "field_name": "form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]",
                "id": "form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]",
                "canonical_questionnaire_id": "p3_5.lea_unit_number",
                "questionnaire_item_id": "p3_5",
                "questionnaire_field_id": "lea_unit_number",
                "answer_field_id": "lea_unit_number",
                "field_type": "text",
                "field_label": "Number",
                "questionnaire_item_type": "text",
            }
        ]

        results = service._build_results_from_answers(
            targets,
            {"p3_5": {"lea_unit_number": "Some value"}},
        )

        self.assertEqual(
            results["form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]"]["value"],
            "",
        )
        self.assertIn(
            "intentionally left blank",
            results["form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]"]["justification"],
        )

    def test_build_results_from_answers_skips_lea_unit_number_when_mismapped_to_agency(self) -> None:
        targets = [
            {
                "field_name": "form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]",
                "id": "form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]",
                "canonical_questionnaire_id": "p3_5.lea_agency_office",
                "questionnaire_item_id": "p3_5",
                "questionnaire_field_id": "lea_agency_office",
                "answer_field_id": "lea_agency_office",
                "field_type": "text",
                "field_label": "Number",
                "questionnaire_item_type": "text",
            }
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "p3_5": {
                    "lea_agency_office": "Human Trafficking Prosecution Unit of the U.S. Department of Justice",
                }
            },
        )

        self.assertEqual(
            results["form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]"]["value"],
            "",
        )
        self.assertIn(
            "intentionally left blank",
            results["form1[0].#subform[4].P3_Line5_AptSteFlrNumber[0]"]["justification"],
        )

    def test_build_results_from_answers_splits_compound_given_name_for_two_given_two_surnames(self) -> None:
        targets = [
            {
                "field_name": "family_name_1",
                "id": "family_name_1",
                "canonical_questionnaire_id": "part1_name.family_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "family_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Family Name (Last Name)",
                "page_number": 1,
            },
            {
                "field_name": "given_name_1",
                "id": "given_name_1",
                "canonical_questionnaire_id": "part1_name.given_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "given_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Given Name (First Name)",
                "page_number": 1,
            },
            {
                "field_name": "middle_name_1",
                "id": "middle_name_1",
                "canonical_questionnaire_id": "part1_name.middle_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "middle_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Middle Name",
                "page_number": 1,
            },
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "shared.name": {
                    "given_name": "Jose Maria",
                    "middle_name": "",
                    "family_name": "Garcia Lopez",
                }
            },
        )

        self.assertEqual(results["family_name_1"]["value"], "Garcia Lopez")
        self.assertEqual(results["given_name_1"]["value"], "Jose")
        self.assertEqual(results["middle_name_1"]["value"], "Maria")

    def test_build_results_from_answers_keeps_compound_given_name_when_family_name_is_not_two_surnames(self) -> None:
        targets = [
            {
                "field_name": "family_name_1",
                "id": "family_name_1",
                "canonical_questionnaire_id": "part1_name.family_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "family_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Family Name (Last Name)",
                "page_number": 1,
            },
            {
                "field_name": "given_name_1",
                "id": "given_name_1",
                "canonical_questionnaire_id": "part1_name.given_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "given_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Given Name (First Name)",
                "page_number": 1,
            },
            {
                "field_name": "middle_name_1",
                "id": "middle_name_1",
                "canonical_questionnaire_id": "part1_name.middle_name",
                "questionnaire_item_id": "part1_name",
                "questionnaire_field_id": "middle_name",
                "questionnaire_section": "Part 1. Information About You",
                "questionnaire_form_text": "Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Middle Name",
                "page_number": 1,
            },
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "shared.name": {
                    "given_name": "Luis Alfonso",
                    "middle_name": "",
                    "family_name": "Ramirez",
                }
            },
        )

        self.assertEqual(results["family_name_1"]["value"], "Ramirez")
        self.assertEqual(results["given_name_1"]["value"], "Luis Alfonso")
        self.assertEqual(results["middle_name_1"]["value"], "")

    def test_extract_values_for_targets_sync_splits_compound_given_name_for_questionnaire_autofill(self) -> None:
        targets = [
            {
                "id": "shared.name.family_name",
                "field_name": "shared.name.family_name",
                "canonical_questionnaire_id": "shared.name.family_name",
                "questionnaire_item_id": "shared.name",
                "questionnaire_field_id": "family_name",
                "questionnaire_section": "Basic Identity",
                "questionnaire_form_text": "Your Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Family Name (Last Name)",
                "page_number": 1,
            },
            {
                "id": "shared.name.given_name",
                "field_name": "shared.name.given_name",
                "canonical_questionnaire_id": "shared.name.given_name",
                "questionnaire_item_id": "shared.name",
                "questionnaire_field_id": "given_name",
                "questionnaire_section": "Basic Identity",
                "questionnaire_form_text": "Your Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Given Name (First Name)",
                "page_number": 1,
            },
            {
                "id": "shared.name.middle_name",
                "field_name": "shared.name.middle_name",
                "canonical_questionnaire_id": "shared.name.middle_name",
                "questionnaire_item_id": "shared.name",
                "questionnaire_field_id": "middle_name",
                "questionnaire_section": "Basic Identity",
                "questionnaire_form_text": "Your Full Legal Name",
                "questionnaire_responsible_party": "client",
                "field_type": "text",
                "field_label": "Middle Name",
                "page_number": 1,
            },
        ]
        settings = SimpleNamespace(autopilot_batch_size=10)
        batch_results = [
            {
                "id": "shared.name.family_name",
                "value": "Garcia Lopez",
                "confidence": "high",
                "justification": "Matched the passport.",
            },
            {
                "id": "shared.name.given_name",
                "value": "Jose Maria",
                "confidence": "high",
                "justification": "Matched the passport.",
            },
            {
                "id": "shared.name.middle_name",
                "value": "",
                "confidence": "high",
                "justification": "Passport does not use a separate middle-name field.",
            },
        ]

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "extract_field_values_batch", return_value=batch_results),
        ):
            results_by_id, extraction_error_count, error_breakdown = service._extract_values_for_targets_sync(
                targets,
                evidence_by_id={},
                form_type="i-914",
                tracker=SimpleNamespace(),
            )

        self.assertEqual(extraction_error_count, 0)
        self.assertEqual(error_breakdown, {})
        self.assertEqual(results_by_id["shared.name.family_name"]["value"], "Garcia Lopez")
        self.assertEqual(results_by_id["shared.name.given_name"]["value"], "Jose")
        self.assertEqual(results_by_id["shared.name.middle_name"]["value"], "Maria")

    def test_build_results_from_answers_infers_last_entry_state_from_city(self) -> None:
        targets = [
            {
                "id": "last_entry_city_field",
                "field_name": "last_entry_city_field",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "canonical_questionnaire_id": "p2_last_entry.last_entry_city",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
                "field_type": "text",
            },
            {
                "id": "last_entry_state_field",
                "field_name": "last_entry_state_field",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "canonical_questionnaire_id": "p2_last_entry.last_entry_state",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
                "field_type": "select",
            },
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "p2_last_entry": {
                    "last_entry_city": "Laredo",
                    "last_entry_state": "",
                }
            },
        )

        self.assertEqual(results["last_entry_city_field"]["value"], "Laredo")
        self.assertEqual(results["last_entry_state_field"]["value"], "TX")
        self.assertIn(
            "Inferred state from city 'Laredo'.",
            results["last_entry_state_field"]["justification"],
        )

    def test_build_results_from_answers_replaces_invalid_last_entry_state_with_city_inference(self) -> None:
        targets = [
            {
                "id": "last_entry_city_field",
                "field_name": "last_entry_city_field",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "canonical_questionnaire_id": "p2_last_entry.last_entry_city",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
                "field_type": "text",
            },
            {
                "id": "last_entry_state_field",
                "field_name": "last_entry_state_field",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "canonical_questionnaire_id": "p2_last_entry.last_entry_state",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
                "field_type": "select",
            },
        ]

        results = service._build_results_from_answers(
            targets,
            {
                "p2_last_entry": {
                    "last_entry_city": "Laredo",
                    "last_entry_state": "Mexico",
                }
            },
        )

        self.assertEqual(results["last_entry_city_field"]["value"], "Laredo")
        self.assertEqual(results["last_entry_state_field"]["value"], "TX")
        self.assertIn(
            "Inferred state from city 'Laredo'.",
            results["last_entry_state_field"]["justification"],
        )

    def test_build_extraction_targets_fallback_maps_i914_part3_reporting_city_and_circumstances(self) -> None:
        city_field_name = "form1[0].#subform[4].P3_Line5_CityOrTown[0]"
        circumstances_field_name = "form1[0].#subform[4].P3_Line5_Circumstances[0]"
        pdf_fields = [
            {
                "field_name": city_field_name,
                "field_label": (
                    "Part 3. Additional Information About Your Application. 5. Law Enforcement "
                    "Agency and Office. Enter City or Town."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 3,
                "nearby_text": "Law Enforcement Agency and Office | City or Town | State | ZIP Code",
                "button_values": [],
                "choice_values": [],
            },
            {
                "field_name": circumstances_field_name,
                "field_label": (
                    "Part 3. Additional Information About Your Application. I have reported the "
                    "trafficking crime of which I am claiming to be a victim. 5. Law Enforcement "
                    "Agency and Office. Enter Circumstances."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 3,
                "nearby_text": "If you selected No, explain the circumstances below.",
                "button_values": [],
                "choice_values": [],
            },
        ]
        mappings = [
            {
                "field_name": city_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": circumstances_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "p3_5.lea_city",
                "item_id": "p3_5",
                "item_code": "3.5",
                "item_type": "text",
                "page_number": 3,
                "label": "City or Town",
                "form_text": "I have reported the trafficking crime of which I am claiming to be a victim.",
                "section": "Part 3. Additional Information About Your Application (continued)",
                "responsible_party": "client",
                "field_id": "lea_city",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
            {
                "canonical_questionnaire_id": "p3_5.lea_circumstances",
                "item_id": "p3_5",
                "item_code": "3.5",
                "item_type": "textarea",
                "page_number": 3,
                "label": "Circumstances",
                "form_text": "I have reported the trafficking crime of which I am claiming to be a victim.",
                "section": "Part 3. Additional Information About Your Application (continued)",
                "responsible_party": "client",
                "field_id": "lea_circumstances",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        by_field_name = {target["field_name"]: target for target in targets}
        city_target = by_field_name[city_field_name]
        circumstances_target = by_field_name[circumstances_field_name]

        self.assertEqual(city_target["canonical_questionnaire_id"], "p3_5.lea_city")
        self.assertEqual(city_target["questionnaire_item_id"], "p3_5")
        self.assertEqual(city_target["questionnaire_field_id"], "lea_city")
        self.assertEqual(circumstances_target["canonical_questionnaire_id"], "p3_5.lea_circumstances")
        self.assertEqual(circumstances_target["questionnaire_item_id"], "p3_5")
        self.assertEqual(circumstances_target["questionnaire_field_id"], "lea_circumstances")

    def test_build_extraction_targets_fallback_maps_i914_part3_lea_state_zip_case(self) -> None:
        state_field_name = "form1[0].#subform[4].P3_Line5_State[0]"
        zip_field_name = "form1[0].#subform[4].P3_Line5_ZIPCode[0]"
        case_field_name = "form1[0].#subform[4].P3_Line5_CaseNumber[0]"
        pdf_fields = [
            {
                "field_name": state_field_name,
                "field_label": (
                    "Part 3. Additional Information About Your Application. 5. Law Enforcement "
                    "Agency and Office. Enter State."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 3,
                "nearby_text": "City or Town | State | ZIP Code",
                "button_values": [],
                "choice_values": [],
            },
            {
                "field_name": zip_field_name,
                "field_label": (
                    "Part 3. Additional Information About Your Application. 5. Law Enforcement "
                    "Agency and Office. Enter ZIP Code."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 3,
                "nearby_text": "City or Town | State | ZIP Code",
                "button_values": [],
                "choice_values": [],
            },
            {
                "field_name": case_field_name,
                "field_label": (
                    "Part 3. Additional Information About Your Application. 5. Law Enforcement "
                    "Agency and Office. Enter Case Number."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 3,
                "nearby_text": "Daytime Telephone Number | Case Number",
                "button_values": [],
                "choice_values": [],
            },
        ]
        mappings = [
            {
                "field_name": state_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": zip_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": case_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
        ]
        _lea_base = {
            "item_id": "p3_5",
            "item_code": "3.5",
            "page_number": 3,
            "form_text": "I have reported the trafficking crime of which I am claiming to be a victim.",
            "section": "Part 3. Additional Information About Your Application (continued)",
            "responsible_party": "client",
            "option_value": None,
            "option_label": None,
            "source_file": "i914_form_client.json",
        }
        questionnaire_definitions = [
            {**_lea_base, "canonical_questionnaire_id": "p3_5.lea_city", "item_type": "text", "label": "City or Town", "field_id": "lea_city"},
            {**_lea_base, "canonical_questionnaire_id": "p3_5.lea_circumstances", "item_type": "textarea", "label": "Circumstances", "field_id": "lea_circumstances"},
            {**_lea_base, "canonical_questionnaire_id": "p3_5.lea_case_number", "item_type": "text", "label": "Case Number", "field_id": "lea_case_number"},
            {**_lea_base, "canonical_questionnaire_id": "p3_5.lea_state", "item_type": "select", "label": "State", "field_id": "lea_state"},
            {**_lea_base, "canonical_questionnaire_id": "p3_5.lea_zip_code", "item_type": "text", "label": "ZIP Code", "field_id": "lea_zip_code"},
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        by_field_name = {target["field_name"]: target for target in targets}
        self.assertEqual(by_field_name[case_field_name]["canonical_questionnaire_id"], "p3_5.lea_case_number")
        self.assertEqual(by_field_name[state_field_name]["canonical_questionnaire_id"], "p3_5.lea_state")
        self.assertEqual(by_field_name[zip_field_name]["canonical_questionnaire_id"], "p3_5.lea_zip_code")

    def test_build_extraction_targets_fallback_maps_i914_last_entry_city_and_state(self) -> None:
        city_field_name = "form1[0].#subform[0].P1_Line17_CityOrTown[0]"
        state_field_name = "form1[0].#subform[0].P1_Line17_State[0]"
        pdf_fields = [
            {
                "field_name": city_field_name,
                "field_label": (
                    "Part 2. General Information About You. Place of Your Last Entry Into the "
                    "United States - City or Town."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 2,
                "nearby_text": "Last Entry Into the United States | City or Town | State",
                "button_values": [],
                "choice_values": [],
            },
            {
                "field_name": state_field_name,
                "field_label": (
                    "Part 2. General Information About You. Place of Your Last Entry Into the "
                    "United States - State."
                ),
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 2,
                "nearby_text": "Last Entry Into the United States | City or Town | State",
                "button_values": [],
                "choice_values": [],
            },
        ]
        mappings = [
            {
                "field_name": city_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": state_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "p2_last_entry.last_entry_city",
                "item_id": "p2_last_entry",
                "item_code": "2.17-2.19",
                "item_type": "text",
                "page_number": 2,
                "label": "Place of Your Last Entry Into the United States - City or Town",
                "form_text": "Last Entry Into the United States",
                "section": "Part 2. General Information About You (continued)",
                "responsible_party": "client",
                "field_id": "last_entry_city",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
            {
                "canonical_questionnaire_id": "p2_last_entry.last_entry_state",
                "item_id": "p2_last_entry",
                "item_code": "2.17-2.19",
                "item_type": "select",
                "page_number": 2,
                "label": "Place of Your Last Entry Into the United States - State",
                "form_text": "Last Entry Into the United States",
                "section": "Part 2. General Information About You (continued)",
                "responsible_party": "client",
                "field_id": "last_entry_state",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        by_field_name = {target["field_name"]: target for target in targets}
        self.assertEqual(by_field_name[city_field_name]["canonical_questionnaire_id"], "p2_last_entry.last_entry_city")
        self.assertEqual(by_field_name[state_field_name]["canonical_questionnaire_id"], "p2_last_entry.last_entry_state")

    def test_build_extraction_targets_fallback_maps_i914_prior_entry_city_and_state(self) -> None:
        city_field_name = "form1[0].#subform[4].P3_Line8_PlaceOfEntryCity[0]"
        state_field_name = "form1[0].#subform[4].P3_Line8_PlaceOfEntryState[0]"
        pdf_fields = [
            {
                "field_name": city_field_name,
                "field_label": "Part 3. Place of Entry - City or Town.",
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 4,
                "nearby_text": (
                    "Part 3. Additional Information About Your Application | This is the first time "
                    "I have entered the United States | Place of Entry | City or Town | State"
                ),
                "button_values": [],
                "choice_values": [],
            },
            {
                "field_name": state_field_name,
                "field_label": "Part 3. Place of Entry - State.",
                "field_type": "text",
                "field_type_hint": "text",
                "page_number": 4,
                "nearby_text": (
                    "Part 3. Additional Information About Your Application | This is the first time "
                    "I have entered the United States | Place of Entry | City or Town | State"
                ),
                "button_values": [],
                "choice_values": [],
            },
        ]
        mappings = [
            {
                "field_name": city_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
            {
                "field_name": state_field_name,
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "questionnaire_option_value": None,
                "canonical_questionnaire_id": None,
                "confidence": "low",
                "matched_label": None,
                "matched_section": None,
                "matched_responsible_party": None,
                "source_file": None,
                "match_score": 1.0,
            },
        ]
        questionnaire_definitions = [
            {
                "canonical_questionnaire_id": "p3_8.prior_entry_city",
                "item_id": "p3_8",
                "item_code": "3.8",
                "item_type": "text",
                "page_number": 4,
                "label": "Place of Entry - City or Town",
                "form_text": "This is the first time I have entered the United States.",
                "section": "Part 3. Additional Information About Your Application (continued)",
                "responsible_party": "client",
                "field_id": "prior_entry_city",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
            {
                "canonical_questionnaire_id": "p3_8.prior_entry_state",
                "item_id": "p3_8",
                "item_code": "3.8",
                "item_type": "select",
                "page_number": 4,
                "label": "Place of Entry - State",
                "form_text": "This is the first time I have entered the United States.",
                "section": "Part 3. Additional Information About Your Application (continued)",
                "responsible_party": "client",
                "field_id": "prior_entry_state",
                "option_value": None,
                "option_label": None,
                "source_file": "i914_form_client.json",
            },
        ]

        with patch.object(service, "list_questionnaire_field_definitions", return_value=questionnaire_definitions):
            targets = service._build_extraction_targets("i-914", pdf_fields, mappings)

        by_field_name = {target["field_name"]: target for target in targets}
        self.assertEqual(by_field_name[city_field_name]["canonical_questionnaire_id"], "p3_8.prior_entry_city")
        self.assertEqual(by_field_name[state_field_name]["canonical_questionnaire_id"], "p3_8.prior_entry_state")

    def test_apply_questionnaire_defaults_to_answers_sets_missing_yes_no_default(self) -> None:
        pages = [
            {
                "page": 5,
                "items": [
                    {
                        "id": "p4_4a",
                        "code": "4.4.A",
                        "type": "yes_no",
                        "default_value": "no",
                        "form_text": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                    }
                ],
            }
        ]

        answers = service._apply_questionnaire_defaults_to_answers(pages, {})

        self.assertEqual(answers["p4_4a"], "no")

    def test_apply_questionnaire_defaults_to_answers_keeps_existing_yes_no_answer(self) -> None:
        pages = [
            {
                "page": 5,
                "items": [
                    {
                        "id": "p4_4a",
                        "code": "4.4.A",
                        "type": "yes_no",
                        "default_value": "no",
                        "form_text": "Designated as a terrorist organization under the Immigration and Nationality Act section 219?",
                    }
                ],
            }
        ]

        answers = service._apply_questionnaire_defaults_to_answers(pages, {"p4_4a": "yes"})

        self.assertEqual(answers["p4_4a"], "yes")

    def test_get_questionnaire_answers_with_defaults_forces_i914_no_answers(self) -> None:
        raw_answers = {
            "p4_4a": "yes",
            "p4_7": "yes",
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertEqual(answers["p4_4a"], "no")
        self.assertEqual(answers["p4_7"], "no")

    def test_get_questionnaire_answers_with_defaults_sets_i914_interpreter_language(self) -> None:
        raw_answers = {
            "p6_1": "B",
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertEqual(answers["p6_1"], "B")
        self.assertEqual(answers["p6_1.interpreter_language"], "Spanish")
        self.assertEqual(answers["p7_7"]["interpreter_fluent_language"], "Spanish")

    def test_postprocess_i914_forced_pdf_values_sets_interpreter_language_by_id(self) -> None:
        targets = [
            {
                "id": "form1[0].#subform[7].Pt6Line1b_Language[0]",
                "field_name": "form1[0].#subform[7].Pt6Line1b_Language[0]",
                "field_type": "text",
                "questionnaire_item_id": "p6_1",
                "questionnaire_field_id": "interpreter_language",
                "canonical_questionnaire_id": "p6_1.interpreter_language",
                "questionnaire_option_value": None,
                "field_label": "",
                "nearby_text": "",
            },
        ]
        results: dict[str, dict[str, str]] = {}
        forced_ids = service._postprocess_i914_forced_pdf_values(targets, results)
        self.assertEqual(
            results["form1[0].#subform[7].Pt6Line1b_Language[0]"]["value"],
            "Spanish",
        )
        self.assertIn("form1[0].#subform[7].Pt6Line1b_Language[0]", forced_ids)

    def test_postprocess_i914_forced_pdf_values_falls_back_to_field_context(self) -> None:
        targets = [
            {
                "id": "form1[0].#subform[7].Pt6Line1b_Language[0]",
                "field_name": "form1[0].#subform[7].Pt6Line1b_Language[0]",
                "field_type": "text",
                "questionnaire_item_id": None,
                "questionnaire_field_id": None,
                "canonical_questionnaire_id": None,
                "questionnaire_option_value": None,
                "field_label": "Language (Part 6, Item Number 1.b.)",
                "nearby_text": "The interpreter named in Part 7",
            },
        ]
        results: dict[str, dict[str, str]] = {}
        forced_ids = service._postprocess_i914_forced_pdf_values(targets, results)
        self.assertEqual(
            results["form1[0].#subform[7].Pt6Line1b_Language[0]"]["value"],
            "Spanish",
        )
        self.assertIn("form1[0].#subform[7].Pt6Line1b_Language[0]", forced_ids)

    def test_postprocess_i914_forced_pdf_values_returns_forced_no_ids(self) -> None:
        targets = [
            {
                "id": "form1[0].Dq5a_no[0]",
                "field_name": "form1[0].Dq5a_no[0]",
                "field_type": "checkbox",
                "questionnaire_item_id": "p4_4a",
                "questionnaire_field_id": None,
                "canonical_questionnaire_id": "p4_4a",
                "questionnaire_option_value": "no",
                "field_label": "",
                "nearby_text": "",
            },
        ]
        results: dict[str, dict[str, str]] = {}
        forced_ids = service._postprocess_i914_forced_pdf_values(targets, results)
        self.assertEqual(results["form1[0].Dq5a_no[0]"]["value"], "yes")
        self.assertIn("form1[0].Dq5a_no[0]", forced_ids)

    def test_infer_target_option_value_prefers_field_name_for_yes_no_pairs(self) -> None:
        target = {
            "field_name": "form1[0].#subform[1].Q1_no[0]",
            "field_label": (
                "Part 3. Additional Information. If you answer Yes to Item Numbers 1-4, "
                "attach evidence. 1. I am or have been a victim. Select No."
            ),
            "questionnaire_options": [
                {"value": "yes", "label": "Yes"},
                {"value": "no", "label": "No"},
            ],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }

        self.assertEqual(service._infer_target_option_value(target), "no")

    def test_infer_target_option_value_prefers_select_phrase_over_incorrect_mapping(self) -> None:
        target = {
            "field_name": "checkbox_1",
            "field_label": "Have you reported the trafficking crime? Select No.",
            "questionnaire_options": [
                {"value": "yes", "label": "Yes"},
                {"value": "no", "label": "No"},
            ],
            "questionnaire_option_value": "yes",
            "questionnaire_option_label": "Yes",
        }

        self.assertEqual(service._infer_target_option_value(target), "no")

    def test_infer_target_option_value_distinguishes_female_from_male(self) -> None:
        target = {
            "field_name": "form1[0].#subform[1].Female[0]",
            "field_label": "Part 2. Sex. Select Female.",
            "questionnaire_options": [
                {"value": "Male", "label": "Male"},
                {"value": "Female", "label": "Female"},
            ],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }

        self.assertEqual(service._infer_target_option_value(target), "Female")

    def test_format_resolved_value_for_pdf_turns_ambiguous_exclusive_checkbox_off(self) -> None:
        target = {
            "field_name": "checkbox_unknown",
            "field_label": "Part 3. Question 1.",
            "field_type": "checkbox",
            "questionnaire_item_type": "yes_no",
            "questionnaire_options": [
                {"value": "yes", "label": "Yes"},
                {"value": "no", "label": "No"},
            ],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "yes"), "off")

    def test_format_resolved_value_for_pdf_keeps_single_boolean_checkbox_working(self) -> None:
        target = {
            "field_name": "single_checkbox",
            "field_label": "Check here",
            "field_type": "checkbox",
            "questionnaire_item_type": "checkbox",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "yes"), "yes")

    def test_format_resolved_value_for_pdf_select_to_checkbox_marks_matching_option(self) -> None:
        target_apt = {
            "field_name": "physical_unit_apt",
            "field_label": "Check this box for Apartment",
            "field_type": "checkbox",
            "questionnaire_item_type": "select",
            "questionnaire_options": [
                {"value": "Apt.", "label": "Apt."},
                {"value": "Ste.", "label": "Ste."},
                {"value": "Flr.", "label": "Flr."},
            ],
            "questionnaire_option_value": "Apt.",
            "questionnaire_option_label": "Apt.",
        }
        target_ste = {
            **target_apt,
            "field_name": "physical_unit_ste",
            "field_label": "Check this box for Suite",
            "questionnaire_option_value": "Ste.",
            "questionnaire_option_label": "Ste.",
        }
        target_flr = {
            **target_apt,
            "field_name": "physical_unit_flr",
            "field_label": "Check this box for Floor",
            "questionnaire_option_value": "Flr.",
            "questionnaire_option_label": "Flr.",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target_apt, "Apt."), "yes")
        self.assertEqual(service._format_resolved_value_for_pdf(target_ste, "Apt."), "off")
        self.assertEqual(service._format_resolved_value_for_pdf(target_flr, "Apt."), "off")

    def test_format_resolved_value_for_pdf_select_checkbox_without_option_falls_back_to_off(self) -> None:
        target = {
            "field_name": "checkbox_unknown_select",
            "field_label": "Part 2. Address unit type",
            "field_type": "checkbox",
            "questionnaire_item_type": "select",
            "questionnaire_options": [
                {"value": "Apt.", "label": "Apt."},
                {"value": "Ste.", "label": "Ste."},
                {"value": "Flr.", "label": "Flr."},
            ],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
        }
        self.assertEqual(service._format_resolved_value_for_pdf(target, "Apt."), "off")

    def test_format_resolved_value_for_pdf_translates_country_text_to_english(self) -> None:
        target = {
            "field_name": "birth_country",
            "field_label": "Country of Birth",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Country of Birth",
            "questionnaire_form_text": "Biographic Information",
            "questionnaire_section": "Biographic Information",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "EE. UU."), "United States")

    def test_format_resolved_value_for_pdf_keeps_safe_mailing_city_with_uscis_boilerplate(self) -> None:
        target = {
            "field_name": "form1[0].#subform[0].P1_Line8_CityOrTown[0]",
            "field_label": (
                "Part 2. General Information About You (Person filing this application as a victim) "
                "4. Safe Mailing Address. If you do not want U.S. Citizenship and Immigration "
                "Services (USCIS) to send notices about this application to your home address, "
                "you may provide an alternate safe mailing address. Enter City or Town."
            ),
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_item_id": "p2_4",
            "questionnaire_field_id": "safe_city",
            "questionnaire_label": "City or Town",
            "questionnaire_form_text": "Safe Mailing Address",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertFalse(service._looks_like_country_target(target))
        self.assertEqual(service._format_resolved_value_for_pdf(target, "Houston"), "Houston")

    def test_format_resolved_value_for_pdf_matches_spanish_yes_no_checkbox_value(self) -> None:
        target = {
            "field_name": "q1_yes",
            "field_label": "Select Yes",
            "field_type": "checkbox",
            "questionnaire_item_type": "yes_no",
            "questionnaire_options": [
                {"value": "yes", "label": "Yes"},
                {"value": "no", "label": "No"},
            ],
            "questionnaire_option_value": "yes",
            "questionnaire_option_label": "Yes",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Sí"), "yes")

    def test_format_resolved_value_for_pdf_matches_spanish_sex_checkbox_value(self) -> None:
        target = {
            "field_name": "male_checkbox",
            "field_label": "Select Male",
            "field_type": "checkbox",
            "questionnaire_item_type": "single_choice",
            "questionnaire_options": [
                {"value": "Male", "label": "Male"},
                {"value": "Female", "label": "Female"},
            ],
            "questionnaire_option_value": "Male",
            "questionnaire_option_label": "Male",
            "questionnaire_label": "Sex",
            "questionnaire_form_text": "Biographic Information",
            "questionnaire_section": "Biographic Information",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Masculino"), "yes")

    def test_format_resolved_value_for_pdf_translates_spanish_marital_status_text(self) -> None:
        target = {
            "field_name": "marital_status",
            "field_label": "Marital Status",
            "field_type": "text",
            "questionnaire_item_type": "single_choice",
            "questionnaire_options": [
                {"value": "Single", "label": "Single"},
                {"value": "Married", "label": "Married"},
                {"value": "Divorced", "label": "Divorced"},
                {"value": "Widowed", "label": "Widowed"},
            ],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Marital Status",
            "questionnaire_form_text": "Biographic Information",
            "questionnaire_section": "Biographic Information",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Casada"), "Married")

    def test_format_resolved_value_for_pdf_translates_nonimmigrant_status_to_english(self) -> None:
        target = {
            "field_name": "current_nonimmigrant_status",
            "field_label": "Your Current Nonimmigrant Status",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Your Current Nonimmigrant Status",
            "questionnaire_form_text": "Your Current Nonimmigrant Status",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertEqual(
            service._format_resolved_value_for_pdf(target, "sin estatus migratorio"),
            "No Legal Status",
        )

    def test_format_resolved_value_for_pdf_keeps_current_nonimmigrant_status_value(self) -> None:
        target = {
            "field_name": "current_nonimmigrant_status",
            "field_label": "Your Current Nonimmigrant Status",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Your Current Nonimmigrant Status",
            "questionnaire_form_text": "Your Current Nonimmigrant Status",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertEqual(
            service._format_resolved_value_for_pdf(target, "B-2 overstay"),
            "B-2 overstay",
        )

    def test_format_resolved_value_for_pdf_blanks_country_copied_into_nonimmigrant_status(self) -> None:
        target = {
            "field_name": "current_nonimmigrant_status",
            "field_label": "Your Current Nonimmigrant Status",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Your Current Nonimmigrant Status",
            "questionnaire_form_text": "Your Current Nonimmigrant Status",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Mexico"), "")
        self.assertEqual(service._format_resolved_value_for_pdf(target, "Woodside"), "")

    def test_format_resolved_value_for_pdf_normalizes_country_of_citizenship_from_nationality(self) -> None:
        target = {
            "field_name": "citizenship_country",
            "field_label": "Country of Citizenship or Nationality",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Country of Citizenship or Nationality",
            "questionnaire_form_text": "Country of Citizenship or Nationality",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Mexicana"), "Mexico")

    def test_format_resolved_value_for_pdf_blanks_invalid_country_of_citizenship_value(self) -> None:
        target = {
            "field_name": "citizenship_country",
            "field_label": "Country of Citizenship or Nationality",
            "field_type": "text",
            "questionnaire_item_type": "text",
            "questionnaire_options": [],
            "questionnaire_option_value": None,
            "questionnaire_option_label": None,
            "questionnaire_label": "Country of Citizenship or Nationality",
            "questionnaire_form_text": "Country of Citizenship or Nationality",
            "questionnaire_section": "Part 2. General Information About You",
        }

        self.assertEqual(service._format_resolved_value_for_pdf(target, "Woodside"), "")

    def test_postprocess_autofill_results_discards_invalid_country_and_status_carryover(self) -> None:
        targets = [
            {
                "id": "citizenship_country",
                "field_name": "citizenship_country",
                "field_label": "Country of Citizenship or Nationality",
                "questionnaire_field_id": "country",
                "questionnaire_label": "Country of Citizenship or Nationality",
                "questionnaire_form_text": "Country of Citizenship or Nationality",
                "questionnaire_section": "Part 2. General Information About You",
            },
            {
                "id": "current_nonimmigrant_status",
                "field_name": "current_nonimmigrant_status",
                "field_label": "Your Current Nonimmigrant Status",
                "questionnaire_field_id": "current_nonimmigrant_status",
                "questionnaire_label": "Your Current Nonimmigrant Status",
                "questionnaire_form_text": "Your Current Nonimmigrant Status",
                "questionnaire_section": "Part 2. General Information About You",
            },
        ]
        results_by_id = {
            "citizenship_country": {
                "id": "citizenship_country",
                "value": "Woodside",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            },
            "current_nonimmigrant_status": {
                "id": "current_nonimmigrant_status",
                "value": "Mexico",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            },
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["citizenship_country"]["value"], "")
        self.assertEqual(results_by_id["current_nonimmigrant_status"]["value"], "")

    def test_postprocess_autofill_results_derives_structured_address_fields(self) -> None:
        targets = [
            {
                "id": "shared.current_physical_address.street_number_name",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "street_number_name",
                "questionnaire_field_id": "street_number_name",
                "field_label": "Street Number and Name",
                "questionnaire_label": "Street Number and Name",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.unit_type",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "unit_type",
                "questionnaire_field_id": "unit_type",
                "field_label": "Apt./Ste./Flr.",
                "questionnaire_label": "Apt./Ste./Flr.",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.unit_number",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "unit_number",
                "questionnaire_field_id": "unit_number",
                "field_label": "Number",
                "questionnaire_label": "Number",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.city",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "city",
                "questionnaire_field_id": "city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.state",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "state",
                "questionnaire_field_id": "state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.zip_code",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "zip_code",
                "questionnaire_field_id": "zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
        ]
        results_by_id = {
            "shared.current_physical_address.street_number_name": {
                "id": "shared.current_physical_address.street_number_name",
                "value": "Direccion actual: 4856 47th St. Apt. 2A. Woodside, NY. 11377",
                "confidence": "medium",
                "justification": "Found in declaration.",
            },
            "shared.current_physical_address.unit_type": {"id": "shared.current_physical_address.unit_type", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.unit_number": {"id": "shared.current_physical_address.unit_number", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.city": {"id": "shared.current_physical_address.city", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.state": {"id": "shared.current_physical_address.state", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.zip_code": {"id": "shared.current_physical_address.zip_code", "value": "", "confidence": "low", "justification": ""},
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(
            results_by_id["shared.current_physical_address.street_number_name"]["value"],
            "4856 47th St",
        )
        self.assertEqual(results_by_id["shared.current_physical_address.unit_type"]["value"], "Apt.")
        self.assertEqual(results_by_id["shared.current_physical_address.unit_number"]["value"], "2A")
        self.assertEqual(results_by_id["shared.current_physical_address.city"]["value"], "Woodside")
        self.assertEqual(results_by_id["shared.current_physical_address.state"]["value"], "NY")
        self.assertEqual(results_by_id["shared.current_physical_address.zip_code"]["value"], "11377")

    def test_postprocess_autofill_results_does_not_derive_lea_unit_number(self) -> None:
        targets = [
            {
                "id": "p3_5.lea_street_number_name",
                "question_id": "p3_5",
                "answer_field_id": "lea_street_number_name",
                "questionnaire_field_id": "lea_street_number_name",
                "field_label": "Street Number and Name",
                "questionnaire_label": "Street Number and Name",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_unit_type",
                "question_id": "p3_5",
                "answer_field_id": "lea_unit_type",
                "questionnaire_field_id": "lea_unit_type",
                "field_label": "Apt./Ste./Flr.",
                "questionnaire_label": "Apt./Ste./Flr.",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_unit_number",
                "question_id": "p3_5",
                "answer_field_id": "lea_unit_number",
                "questionnaire_field_id": "lea_unit_number",
                "field_label": "Number",
                "questionnaire_label": "Number",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_city",
                "question_id": "p3_5",
                "answer_field_id": "lea_city",
                "questionnaire_field_id": "lea_city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_state",
                "question_id": "p3_5",
                "answer_field_id": "lea_state",
                "questionnaire_field_id": "lea_state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_zip_code",
                "question_id": "p3_5",
                "answer_field_id": "lea_zip_code",
                "questionnaire_field_id": "lea_zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
        ]
        results_by_id = {
            "p3_5.lea_street_number_name": {
                "id": "p3_5.lea_street_number_name",
                "value": "950 Pennsylvania Ave NW Ste. 200, Washington, DC 20530",
                "confidence": "medium",
                "justification": "Found in declaration.",
            },
            "p3_5.lea_unit_type": {"id": "p3_5.lea_unit_type", "value": "", "confidence": "low", "justification": ""},
            "p3_5.lea_unit_number": {"id": "p3_5.lea_unit_number", "value": "", "confidence": "low", "justification": ""},
            "p3_5.lea_city": {"id": "p3_5.lea_city", "value": "", "confidence": "low", "justification": ""},
            "p3_5.lea_state": {"id": "p3_5.lea_state", "value": "", "confidence": "low", "justification": ""},
            "p3_5.lea_zip_code": {"id": "p3_5.lea_zip_code", "value": "", "confidence": "low", "justification": ""},
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["p3_5.lea_street_number_name"]["value"], "950 Pennsylvania Ave NW")
        self.assertEqual(results_by_id["p3_5.lea_unit_type"]["value"], "Ste.")
        self.assertEqual(results_by_id["p3_5.lea_unit_number"]["value"], "")
        self.assertEqual(results_by_id["p3_5.lea_city"]["value"], "Washington")
        self.assertEqual(results_by_id["p3_5.lea_state"]["value"], "DC")
        self.assertEqual(results_by_id["p3_5.lea_zip_code"]["value"], "20530")

    def test_postprocess_autofill_results_keeps_online_submission_lea_fields(self) -> None:
        targets = [
            {
                "id": "p3_5.lea_street_number_name",
                "question_id": "p3_5",
                "answer_field_id": "lea_street_number_name",
                "questionnaire_field_id": "lea_street_number_name",
                "field_label": "Street Number and Name",
                "questionnaire_label": "Street Number and Name",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_city",
                "question_id": "p3_5",
                "answer_field_id": "lea_city",
                "questionnaire_field_id": "lea_city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_state",
                "question_id": "p3_5",
                "answer_field_id": "lea_state",
                "questionnaire_field_id": "lea_state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
            {
                "id": "p3_5.lea_zip_code",
                "question_id": "p3_5",
                "answer_field_id": "lea_zip_code",
                "questionnaire_field_id": "lea_zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Law Enforcement Agency and Office",
                "questionnaire_section": "Part 3. Additional Information About Your Application",
            },
        ]
        results_by_id = {
            "p3_5.lea_street_number_name": {
                "id": "p3_5.lea_street_number_name",
                "value": "Human Trafficking Prosecution Unit, U.S Department of Justice",
                "confidence": "high",
                "justification": "Saved questionnaire answer from p3_5.lea_street_number_name.",
            },
            "p3_5.lea_city": {
                "id": "p3_5.lea_city",
                "value": "Online Submission",
                "confidence": "high",
                "justification": "Saved questionnaire answer from p3_5.lea_city.",
            },
            "p3_5.lea_state": {"id": "p3_5.lea_state", "value": "", "confidence": "low", "justification": ""},
            "p3_5.lea_zip_code": {"id": "p3_5.lea_zip_code", "value": "", "confidence": "low", "justification": ""},
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(
            results_by_id["p3_5.lea_street_number_name"]["value"],
            "Human Trafficking Prosecution Unit, U.S Department of Justice",
        )
        self.assertEqual(results_by_id["p3_5.lea_city"]["value"], "Online Submission")
        self.assertEqual(results_by_id["p3_5.lea_state"]["value"], "")
        self.assertEqual(results_by_id["p3_5.lea_zip_code"]["value"], "")

    def test_postprocess_autofill_results_recovers_physical_address_from_question_answer_dump(self) -> None:
        targets = [
            {
                "id": "shared.current_physical_address.street_number_name",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "street_number_name",
                "questionnaire_field_id": "street_number_name",
                "field_label": "Street Number and Name",
                "questionnaire_label": "Street Number and Name",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.unit_type",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "unit_type",
                "questionnaire_field_id": "unit_type",
                "field_label": "Apt./Ste./Flr.",
                "questionnaire_label": "Apt./Ste./Flr.",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.unit_number",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "unit_number",
                "questionnaire_field_id": "unit_number",
                "field_label": "Number",
                "questionnaire_label": "Number",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.city",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "city",
                "questionnaire_field_id": "city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.state",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "state",
                "questionnaire_field_id": "state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
            {
                "id": "shared.current_physical_address.zip_code",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "zip_code",
                "questionnaire_field_id": "zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
            },
        ]
        qa_dump = (
            "Pregunta: 1. Informacion Biografica - Fecha de ingreso Respuesta: septiembre, 2016 "
            "Pregunta: 1. Informacion Biografica - Direccion actual Respuesta: "
            "4856 47th St. Apt. 2A. Woodside, NY. 11377"
        )
        results_by_id = {
            "shared.current_physical_address.street_number_name": {
                "id": "shared.current_physical_address.street_number_name",
                "value": qa_dump,
                "confidence": "high",
                "justification": "Model copied the full intake block.",
            },
            "shared.current_physical_address.unit_type": {"id": "shared.current_physical_address.unit_type", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.unit_number": {"id": "shared.current_physical_address.unit_number", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.city": {"id": "shared.current_physical_address.city", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.state": {"id": "shared.current_physical_address.state", "value": "", "confidence": "low", "justification": ""},
            "shared.current_physical_address.zip_code": {"id": "shared.current_physical_address.zip_code", "value": "", "confidence": "low", "justification": ""},
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(
            results_by_id["shared.current_physical_address.street_number_name"]["value"],
            "4856 47th St",
        )
        self.assertEqual(results_by_id["shared.current_physical_address.unit_type"]["value"], "Apt.")
        self.assertEqual(results_by_id["shared.current_physical_address.unit_number"]["value"], "2A")
        self.assertEqual(results_by_id["shared.current_physical_address.city"]["value"], "Woodside")
        self.assertEqual(results_by_id["shared.current_physical_address.state"]["value"], "NY")
        self.assertEqual(results_by_id["shared.current_physical_address.zip_code"]["value"], "11377")

    def test_postprocess_autofill_results_recovers_passport_issue_date(self) -> None:
        target = {
            "id": "p2_passport.passport_issue_date",
            "question_id": "p2_passport",
            "answer_field_id": "passport_issue_date",
            "questionnaire_field_id": "passport_issue_date",
            "field_label": "Issue Date for Passport or Travel Document (if any)",
            "questionnaire_label": "Issue Date for Passport or Travel Document (if any)",
            "questionnaire_form_text": "Passport or Travel Document Information",
            "questionnaire_section": "Part 2. General Information About You",
        }
        results_by_id = {
            "p2_passport.passport_issue_date": {
                "id": "p2_passport.passport_issue_date",
                "value": "",
                "confidence": "low",
                "justification": "",
            }
        }
        evidence_by_id = {
            "p2_passport.passport_issue_date": {
                "text_context": "Pasaporte. Fecha de expedicion: 15 ABR 2021. Fecha de vencimiento: 14 ABR 2031."
            }
        }

        service._postprocess_autofill_results([target], results_by_id, evidence_by_id)

        self.assertEqual(results_by_id["p2_passport.passport_issue_date"]["value"], "Apr 15 2021")

    def test_postprocess_autofill_results_discards_invalid_a_number(self) -> None:
        target = {
            "id": "shared.identifiers.a_number",
            "question_id": "shared.identifiers",
            "answer_field_id": "a_number",
            "questionnaire_field_id": "a_number",
            "field_label": "Alien Registration Number (A-Number)",
            "questionnaire_label": "Alien Registration Number (A-Number)",
            "questionnaire_form_text": "Government Identifiers",
            "questionnaire_section": "Basic Identity",
        }
        results_by_id = {
            "shared.identifiers.a_number": {
                "id": "shared.identifiers.a_number",
                "value": "Marisol Ramirez",
                "confidence": "high",
                "justification": "Model guessed a value.",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, {})

        self.assertEqual(results_by_id["shared.identifiers.a_number"]["value"], "")

    def test_postprocess_autofill_results_clears_duplicate_safe_mailing_address(self) -> None:
        targets = [
            {
                "id": "shared.current_physical_address.street_number_name",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "street_number_name",
                "questionnaire_field_id": "street_number_name",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
            {
                "id": "shared.current_physical_address.city",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "city",
                "questionnaire_field_id": "city",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
            {
                "id": "shared.current_physical_address.state",
                "question_id": "shared.current_physical_address",
                "answer_field_id": "state",
                "questionnaire_field_id": "state",
                "questionnaire_form_text": "Current Physical Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
            {
                "id": "shared.safe_mailing_address.street_number_name",
                "question_id": "shared.safe_mailing_address",
                "answer_field_id": "street_number_name",
                "questionnaire_field_id": "street_number_name",
                "questionnaire_form_text": "Safe Mailing Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
            {
                "id": "shared.safe_mailing_address.city",
                "question_id": "shared.safe_mailing_address",
                "answer_field_id": "city",
                "questionnaire_field_id": "city",
                "questionnaire_form_text": "Safe Mailing Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
            {
                "id": "shared.safe_mailing_address.state",
                "question_id": "shared.safe_mailing_address",
                "answer_field_id": "state",
                "questionnaire_field_id": "state",
                "questionnaire_form_text": "Safe Mailing Address",
                "questionnaire_section": "Address Information",
                "page_number": 3,
            },
        ]
        results_by_id = {
            "shared.current_physical_address.street_number_name": {"id": "shared.current_physical_address.street_number_name", "value": "4856 47th St", "confidence": "high", "justification": ""},
            "shared.current_physical_address.city": {"id": "shared.current_physical_address.city", "value": "Woodside", "confidence": "high", "justification": ""},
            "shared.current_physical_address.state": {"id": "shared.current_physical_address.state", "value": "NY", "confidence": "high", "justification": ""},
            "shared.safe_mailing_address.street_number_name": {"id": "shared.safe_mailing_address.street_number_name", "value": "4856 47th St", "confidence": "medium", "justification": ""},
            "shared.safe_mailing_address.city": {"id": "shared.safe_mailing_address.city", "value": "Woodside", "confidence": "medium", "justification": ""},
            "shared.safe_mailing_address.state": {"id": "shared.safe_mailing_address.state", "value": "NY", "confidence": "medium", "justification": ""},
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["shared.safe_mailing_address.street_number_name"]["value"], "")
        self.assertEqual(results_by_id["shared.safe_mailing_address.city"]["value"], "")
        self.assertEqual(results_by_id["shared.safe_mailing_address.state"]["value"], "")

    def test_postprocess_autofill_results_discards_physical_address_dump_from_safe_mailing(self) -> None:
        target = {
            "id": "shared.safe_mailing_address.street_number_name",
            "question_id": "shared.safe_mailing_address",
            "answer_field_id": "street_number_name",
            "questionnaire_field_id": "street_number_name",
            "field_label": "Street Number and Name",
            "questionnaire_label": "Street Number and Name",
            "questionnaire_form_text": "Safe Mailing Address",
            "questionnaire_section": "Address Information",
            "page_number": 3,
        }
        results_by_id = {
            "shared.safe_mailing_address.street_number_name": {
                "id": "shared.safe_mailing_address.street_number_name",
                "value": (
                    "Pregunta: 1. Informacion Biografica - Fecha de ingreso Respuesta: septiembre, 2016 "
                    "Pregunta: 1. Informacion Biografica - Direccion actual Respuesta: 4856 47th St"
                ),
                "confidence": "high",
                "justification": "Model copied the full intake block.",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, {})

        self.assertEqual(results_by_id["shared.safe_mailing_address.street_number_name"]["value"], "")

    def test_postprocess_autofill_results_discards_country_copied_into_prior_entry_status(self) -> None:
        target = {
            "id": "p3_8.prior_entry_status",
            "question_id": "p3_8",
            "answer_field_id": "prior_entry_status",
            "questionnaire_field_id": "prior_entry_status",
            "field_label": "Status",
            "questionnaire_label": "Status",
            "questionnaire_form_text": "Prior Entries into the United States",
            "questionnaire_section": "Part 3. Additional Information About Your Application",
        }
        results_by_id = {
            "p3_8.prior_entry_status": {
                "id": "p3_8.prior_entry_status",
                "value": "Mexico",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, {})

        self.assertEqual(results_by_id["p3_8.prior_entry_status"]["value"], "")

    def test_postprocess_autofill_results_discards_date_copied_into_city(self) -> None:
        target = {
            "id": "shared.current_physical_address.city",
            "question_id": "shared.current_physical_address",
            "answer_field_id": "city",
            "questionnaire_field_id": "city",
            "field_label": "City or Town",
            "questionnaire_label": "City or Town",
            "questionnaire_form_text": "Current Physical Address",
            "questionnaire_section": "Address Information",
            "page_number": 3,
        }
        results_by_id = {
            "shared.current_physical_address.city": {
                "id": "shared.current_physical_address.city",
                "value": "01/02/2020",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, {})

        self.assertEqual(results_by_id["shared.current_physical_address.city"]["value"], "")
        self.assertEqual(results_by_id["shared.current_physical_address.city"]["confidence"], "low")
        self.assertIn("looked like a date", results_by_id["shared.current_physical_address.city"]["justification"])

    def test_postprocess_autofill_results_discards_phone_copied_into_case_number(self) -> None:
        target = {
            "id": "p3_5.case_number",
            "question_id": "p3_5",
            "answer_field_id": "case_number",
            "questionnaire_field_id": "case_number",
            "field_label": "Case Number",
            "questionnaire_label": "Case Number",
            "questionnaire_form_text": "Law Enforcement Agency and Office",
            "questionnaire_section": "Part 3. Additional Information About Your Application",
            "page_number": 3,
        }
        results_by_id = {
            "p3_5.case_number": {
                "id": "p3_5.case_number",
                "value": "(212) 555-0101",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            }
        }
        evidence_by_id = {
            "p3_5.case_number": {
                "text_context": "Daytime Telephone Number: (212) 555-0101",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, evidence_by_id)

        self.assertEqual(results_by_id["p3_5.case_number"]["value"], "")
        self.assertEqual(results_by_id["p3_5.case_number"]["confidence"], "low")
        self.assertIn("looked like a phone number", results_by_id["p3_5.case_number"]["justification"])

    def test_postprocess_autofill_results_keeps_phone_like_case_number_when_explicitly_labeled(self) -> None:
        target = {
            "id": "p3_5.case_number",
            "question_id": "p3_5",
            "answer_field_id": "case_number",
            "questionnaire_field_id": "case_number",
            "field_label": "Case Number",
            "questionnaire_label": "Case Number",
            "questionnaire_form_text": "Law Enforcement Agency and Office",
            "questionnaire_section": "Part 3. Additional Information About Your Application",
            "page_number": 3,
        }
        results_by_id = {
            "p3_5.case_number": {
                "id": "p3_5.case_number",
                "value": "(212) 555-0101",
                "confidence": "high",
                "justification": "Matched labeled evidence.",
            }
        }
        evidence_by_id = {
            "p3_5.case_number": {
                "text_context": "Case Number: (212) 555-0101",
            }
        }

        service._postprocess_autofill_results([target], results_by_id, evidence_by_id)

        self.assertEqual(results_by_id["p3_5.case_number"]["value"], "(212) 555-0101")
        self.assertEqual(results_by_id["p3_5.case_number"]["confidence"], "high")

    def test_postprocess_autofill_results_flags_unexpected_duplicate_previous_field(self) -> None:
        targets = [
            {
                "id": "shared.name.family_name",
                "field_name": "shared.name.family_name",
                "field_label": "Family Name",
                "questionnaire_field_id": "family_name",
                "questionnaire_label": "Family Name",
                "questionnaire_form_text": "Legal Name",
                "questionnaire_section": "Biographic Information",
                "page_number": 1,
            },
            {
                "id": "shared.name.given_name",
                "field_name": "shared.name.given_name",
                "field_label": "Given Name",
                "questionnaire_field_id": "given_name",
                "questionnaire_label": "Given Name",
                "questionnaire_form_text": "Legal Name",
                "questionnaire_section": "Biographic Information",
                "page_number": 1,
            },
        ]
        results_by_id = {
            "shared.name.family_name": {
                "id": "shared.name.family_name",
                "value": "Ramirez",
                "confidence": "high",
                "justification": "Matched the intake sheet.",
            },
            "shared.name.given_name": {
                "id": "shared.name.given_name",
                "value": "Ramirez",
                "confidence": "high",
                "justification": "Copied from nearby text.",
            },
        }

        service._postprocess_autofill_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["shared.name.given_name"]["value"], "Ramirez")
        self.assertEqual(results_by_id["shared.name.given_name"]["confidence"], "low")
        self.assertIn(
            "duplicated the previous field unexpectedly",
            results_by_id["shared.name.given_name"]["justification"],
        )

    def test_resolve_questionnaire_answer_falls_back_to_shared_valid_a_number(self) -> None:
        target = {
            "field_name": "form1[0].A_Number[0]",
            "field_label": "Alien Registration Number (A-Number) (if any)",
            "field_type": "text",
            "canonical_questionnaire_id": "p2_5",
            "questionnaire_item_id": "p2_5",
            "questionnaire_field_id": None,
            "questionnaire_label": "Alien Registration Number (A-Number) (if any)",
            "questionnaire_form_text": "Alien Registration Number (A-Number) (if any)",
            "questionnaire_section": "Part 2. General Information About You",
        }
        answers = {
            "p2_5": "Marisol",
            "shared.identifiers": {"a_number": "246813579"},
        }

        value, source = service._resolve_questionnaire_answer(target, answers, occurrence_index=0)

        self.assertEqual(value, "246813579")
        self.assertEqual(source, "shared.identifiers.a_number")

    def test_resolve_questionnaire_answer_blanks_safe_mailing_when_same_as_physical(self) -> None:
        target = {
            "field_name": "shared.safe_mailing_address.city",
            "field_label": "City or Town",
            "field_type": "text",
            "canonical_questionnaire_id": "shared.safe_mailing_address.city",
            "questionnaire_item_id": "shared.safe_mailing_address",
            "questionnaire_field_id": "city",
            "questionnaire_label": "City or Town",
            "questionnaire_form_text": "Safe Mailing Address",
            "questionnaire_section": "Address Information",
        }
        answers = {
            "shared.current_physical_address": {"city": "Woodside"},
            "shared.safe_mailing_address": {"city": "Woodside"},
        }

        value, source = service._resolve_questionnaire_answer(target, answers, occurrence_index=0)

        self.assertEqual(value, "")
        self.assertIsNone(source)

    def test_get_questionnaire_answers_with_defaults_derives_i914_part9_entries_for_required_triggers(self) -> None:
        raw_answers = {
            "p3_1": "yes",
            "p3_5": "no",
            "p3_5.lea_circumstances": "Could not report safely until I relocated.",
            "p2_last_entry": {
                "last_entry_city": "Laredo",
                "last_entry_state": "TX",
                "last_entry_date": "01/02/2020",
            },
            "p3_8": "no",
            "p3_8.prior_entry_date": ["01/02/2020"],
            "p3_8.prior_entry_city": ["San Ysidro"],
            "p3_8.prior_entry_state": ["CA"],
            "p3_8.prior_entry_status": ["B-2"],
            "p3_9": "yes",
            "p3_9.arrival_circumstances": (
                "I entered through the port of entry and was detained and processed before release."
            ),
            "p3_11": "yes",
            "p4_9e": "yes",
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        entries = answers.get("p9_entries")
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 4)

        by_key = {
            (entry["part_number"], entry["item_number"]): entry
            for entry in entries
        }
        self.assertNotIn(("3", "1"), by_key)
        self.assertNotIn(("3", "11"), by_key)
        self.assertIn(("3", "5"), by_key)
        self.assertIn(("3", "8"), by_key)
        self.assertIn(("3", "9"), by_key)
        self.assertIn(("4", "9.E"), by_key)
        self.assertIn(
            "Could not report safely until I relocated.",
            by_key[("3", "5")]["additional_information"],
        )
        self.assertIn(
            "San Ysidro, CA",
            by_key[("3", "8")]["additional_information"],
        )
        self.assertIn(
            "Most recent arrival: Date: Jan 02 2020; Place: Laredo, TX; Circumstances: I entered through the port of entry and was detained and processed before release.",
            by_key[("3", "8")]["additional_information"],
        )
        self.assertIn(
            "Answer: Yes.",
            by_key[("3", "9")]["additional_information"],
        )
        self.assertIn(
            "Most recent arrival: Date: Jan 02 2020; Place: Laredo, TX; Circumstances: I entered through the port of entry and was detained and processed before release.",
            by_key[("3", "9")]["additional_information"],
        )
        self.assertIn(
            "Answer: Yes.",
            by_key[("4", "9.E")]["additional_information"],
        )

    def test_get_questionnaire_answers_with_defaults_includes_part3_explanation_text_when_required(self) -> None:
        raw_answers = {
            "p3_7": "no",
            "p3_7.explanation": "I was over 18 and could not cooperate safely because of severe trauma.",
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        entries = answers.get("p9_entries")
        self.assertIsInstance(entries, list)

        by_key = {
            (entry["part_number"], entry["item_number"]): entry
            for entry in entries
        }
        self.assertIn(("3", "7"), by_key)
        self.assertIn(
            "I was over 18 and could not cooperate safely because of severe trauma.",
            by_key[("3", "7")]["additional_information"],
        )

    def test_get_questionnaire_answers_with_defaults_generates_addendum_for_any_part4_yes(self) -> None:
        raw_answers = {
            "p4_1a": "yes",
            "p4_10b": "yes",
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        entries = answers.get("p9_entries")
        self.assertIsInstance(entries, list)

        by_key = {
            (entry["part_number"], entry["item_number"]): entry
            for entry in entries
        }
        self.assertIn(("4", "1.A"), by_key)
        self.assertIn(("4", "10.B"), by_key)
        self.assertIn("Answer: Yes.", by_key[("4", "1.A")]["additional_information"])
        self.assertIn("Answer: Yes.", by_key[("4", "10.B")]["additional_information"])

    def test_postprocess_i914_critical_field_override_prefers_higher_tier_evidence(self) -> None:
        targets = [
            {
                "id": "last_entry_city_field",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_city",
            },
            {
                "id": "last_entry_state_field",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_state",
            },
            {
                "id": "last_entry_date_field",
                "questionnaire_item_id": "p2_last_entry",
                "questionnaire_field_id": "last_entry_date",
            },
        ]
        results_by_id = {
            "last_entry_city_field": {
                "id": "last_entry_city_field",
                "value": "Brownsville",
                "confidence": "low",
                "justification": "LLM guess.",
            },
            "last_entry_state_field": {
                "id": "last_entry_state_field",
                "value": "TX",
                "confidence": "medium",
                "justification": "LLM guess.",
            },
            "last_entry_date_field": {
                "id": "last_entry_date_field",
                "value": "06/13/2008",
                "confidence": "low",
                "justification": "LLM guess.",
            },
        }

        service._postprocess_i914_critical_field_override(
            targets,
            results_by_id,
            detention_facts={
                "date": "11/18/2022",
                "location": "Laredo, TX",
                "location_city": "Laredo",
                "location_state": "TX",
                "source_tier": "1",
            },
        )

        self.assertEqual(results_by_id["last_entry_city_field"]["value"], "Laredo")
        self.assertEqual(results_by_id["last_entry_state_field"]["value"], "TX")
        self.assertEqual(results_by_id["last_entry_date_field"]["value"], "Nov 18 2022")

    def test_postprocess_address_cross_contamination_clears_safe_mailing_city_carryover(self) -> None:
        targets = [
            {
                "id": "safe_in_care",
                "question_id": "p2_4",
                "questionnaire_item_id": "p2_4",
                "questionnaire_field_id": "in_care_of_name",
                "field_label": "In Care Of Name",
                "questionnaire_form_text": "Safe Mailing Address",
                "questionnaire_label": "In Care Of Name",
            },
            {
                "id": "safe_city",
                "question_id": "p2_4",
                "questionnaire_item_id": "p2_4",
                "questionnaire_field_id": "safe_city",
                "field_label": "City or Town",
                "questionnaire_form_text": "Safe Mailing Address",
                "questionnaire_label": "City or Town",
            },
        ]
        results_by_id = {
            "safe_in_care": {
                "id": "safe_in_care",
                "value": "Law Offices of Manuel E. Solis",
                "confidence": "high",
                "justification": "Recovered from address block.",
            },
            "safe_city": {
                "id": "safe_city",
                "value": "Solis",
                "confidence": "medium",
                "justification": "Nearby OCR text.",
            },
        }

        service._postprocess_address_cross_check(targets, results_by_id)

        self.assertEqual(results_by_id["safe_city"]["value"], "")
        self.assertEqual(results_by_id["safe_city"]["confidence"], "low")
        self.assertIn("carryover", results_by_id["safe_city"]["justification"])

    def test_build_i914_part9_additional_information_uses_factual_text_without_manual_marker(self) -> None:
        text = service._build_i914_part9_additional_information(
            {
                "id": "p4_1b",
                "form_text": "Been arrested, cited, or detained by any law enforcement officer?",
            },
            "yes",
            {
                "p2_last_entry": {
                    "last_entry_city": "Laredo",
                    "last_entry_state": "TX",
                    "last_entry_date": "11/18/2022",
                }
            },
            page_number="4",
            part_number="4",
            item_number="1.B",
        )

        self.assertIn("Question:", text)
        self.assertIn("Answer: Yes.", text)
        self.assertIn("Laredo, TX", text)
        self.assertNotIn("REQUIRES MANUAL COMPLETION", text)
        self.assertNotIn("Details to be provided upon review of supporting documentation.", text)

    def test_get_questionnaire_answers_with_defaults_clears_partial_i914_spouse_group(self) -> None:
        raw_answers = {
            "p5_1": {
                "spouse_family_name": "",
                "spouse_given_name": "Luis",
                "spouse_middle_name": "Alberto",
                "spouse_date_of_birth": "07/05/1989",
                "spouse_country_of_birth": "Honduras",
                "spouse_residence_city": "San Pedro Sula",
                "spouse_residence_country": "Honduras",
            }
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertEqual(answers.get("p5_1"), {})

    def test_get_questionnaire_answers_with_defaults_discards_partial_i914_child_rows(self) -> None:
        raw_answers = {
            "p5_children": [
                {
                    "family_name": "Ramirez Castillo",
                    "given_name": "Sofia",
                    "middle_name": "Luciana",
                    "date_of_birth": "02/14/2016",
                    "country_of_birth": "Honduras",
                    "current_city": "San Pedro Sula",
                    "current_state": "",
                    "current_country": "Honduras",
                },
                {
                    "family_name": "",
                    "given_name": "Mateo",
                    "middle_name": "",
                    "date_of_birth": "09/10/2018",
                    "country_of_birth": "Honduras",
                    "current_city": "San Pedro Sula",
                    "current_state": "",
                    "current_country": "Honduras",
                },
            ]
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        children = answers.get("p5_children")
        self.assertIsInstance(children, list)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]["given_name"], "Sofia")

    def test_get_questionnaire_answers_with_defaults_keeps_manual_i914_part9_entry(self) -> None:
        raw_answers = {
            "p4_9e": "yes",
            "p9_entries": [
                {
                    "page_number": "6",
                    "part_number": "4",
                    "item_number": "9.E",
                    "additional_information": "Manual visa explanation.",
                }
            ],
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        entries = answers.get("p9_entries")
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["additional_information"], "Manual visa explanation.")

    def test_get_questionnaire_answers_with_defaults_backfills_blank_manual_i914_part9_entry(self) -> None:
        raw_answers = {
            "p4_9e": "yes",
            "p9_entries": [
                {
                    "page_number": "6",
                    "part_number": "4",
                    "item_number": "9.E",
                    "additional_information": "",
                }
            ],
        }

        with patch.object(service, "get_questionnaire_answers", return_value=raw_answers):
            answers = service._get_questionnaire_answers_with_defaults(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        entries = answers.get("p9_entries")
        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertIn("Question:", entries[0]["additional_information"])
        self.assertIn("Answer: Yes.", entries[0]["additional_information"])

    def test_validate_part9_completeness_requires_addendum_for_part3_no_answers(self) -> None:
        missing = service._validate_part9_completeness(
            [
                {
                    "id": "p3_8_field",
                    "questionnaire_item_id": "p3_8",
                    "questionnaire_instruction": "If you selected No, explain the circumstances.",
                }
            ],
            {
                "p3_8_field": {
                    "id": "p3_8_field",
                    "value": "no",
                    "confidence": "medium",
                    "justification": "Saved answer.",
                }
            },
            {"p9_entries": []},
        )

        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["item_id"], "p3_8")

    def test_questionnaire_value_type_issue_rejects_country_in_immigration_status(self) -> None:
        issue = service._questionnaire_value_type_issue(
            {
                "id": "shared_passport_and_travel",
                "code": "shared",
                "type": "group",
                "form_text": "Passport and Travel",
                "section": "Shared",
            },
            {
                "id": "current_immigration_status",
                "label": "Current Nonimmigrant Status",
                "type": "text",
            },
            "Honduras",
        )

        self.assertIsNotNone(issue)
        self.assertEqual(issue["code"], "invalid_immigration_status")

    def test_validate_form_generation_requirements_blocks_partial_i914_spouse_data(self) -> None:
        raw_answers = {
            "shared.biographics": {
                "marital_status": "married",
            },
            "p5_1": {
                "spouse_family_name": "",
                "spouse_given_name": "Luis",
                "spouse_middle_name": "Alberto",
                "spouse_date_of_birth": "07/05/1989",
                "spouse_country_of_birth": "Honduras",
                "spouse_residence_city": "San Pedro Sula",
                "spouse_residence_country": "Honduras",
            },
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertTrue(
            any(
                issue["question_id"] == "p5_1"
                and issue["field_id"] == "spouse_family_name"
                and issue["code"] == "missing_required_field"
                for issue in issues
            )
        )

    def test_validate_form_generation_requirements_does_not_block_missing_i914_part4_detail_table(self) -> None:
        raw_answers = {
            "p4_1b": "yes",
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(issue["question_id"] == "p4_1_details" and issue["code"] == "missing_repeatable_entry" for issue in issues)
        )

    def test_validate_form_generation_requirements_does_not_require_optional_i914_defaults(self) -> None:
        raw_answers = {}

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        blocked_fields = {
            (issue["question_id"], issue["field_id"])
            for issue in issues
        }
        self.assertNotIn(("p3_5", "lea_agency_office"), blocked_fields)
        self.assertNotIn(("p3_5", "lea_state"), blocked_fields)
        self.assertNotIn(("p3_5", "lea_zip_code"), blocked_fields)
        self.assertNotIn(("p3_9", "arrival_circumstances"), blocked_fields)

    def test_questionnaire_condition_applies_supports_non_yes_no_patterns(self) -> None:
        self.assertFalse(
            service._questionnaire_condition_applies(
                {"id": "p6_1"},
                "If option 'B' is selected",
                {},
            )
        )
        self.assertTrue(
            service._questionnaire_condition_applies(
                {"id": "p6_1"},
                "If option 'B' is selected",
                {"p6_1": "B"},
            )
        )

        checkbox_item = {
            "id": "p6_2",
            "fields": [
                {
                    "id": "preparer_statement_selected",
                    "type": "checkbox",
                }
            ],
        }
        self.assertFalse(
            service._questionnaire_condition_applies(
                checkbox_item,
                "If the checkbox is selected",
                {},
            )
        )
        self.assertTrue(
            service._questionnaire_condition_applies(
                checkbox_item,
                "If the checkbox is selected",
                {"p6_2": {"preparer_statement_selected": True}},
            )
        )

        self.assertFalse(
            service._questionnaire_condition_applies(
                {"id": "p7_7"},
                "If an interpreter was used / if 6.1.B is selected",
                {},
            )
        )
        self.assertTrue(
            service._questionnaire_condition_applies(
                {"id": "p7_7"},
                "If an interpreter was used / if 6.1.B is selected",
                {"p6_1": "B"},
            )
        )

    def test_field_is_required_for_generation_validation_skips_signature_fields(self) -> None:
        item = {
            "id": "p7_7",
            "form_text": "Interpreter's Certification and Signature",
        }
        self.assertFalse(
            service._field_required_for_generation(
                item,
                {
                    "id": "interpreter_signature",
                    "label": "Interpreter's Signature",
                    "type": "signature",
                },
            )
        )
        self.assertFalse(
            service._field_required_for_generation(
                item,
                {
                    "id": "interpreter_signature_date",
                    "label": "Date of Signature",
                    "type": "date",
                },
            )
        )

    def test_validate_form_generation_requirements_respects_non_yes_no_i914_conditions(self) -> None:
        raw_answers = {}

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        blocked_fields = {
            (issue["question_id"], issue["field_id"])
            for issue in issues
        }
        self.assertNotIn(("p6_1", "interpreter_language"), blocked_fields)
        self.assertNotIn(("p6_2", "preparer_name_in_statement"), blocked_fields)
        self.assertNotIn(("p7_7", "interpreter_signature"), blocked_fields)
        self.assertNotIn(("p7_7", "interpreter_signature_date"), blocked_fields)

    def test_validate_form_generation_requirements_ignores_default_only_optional_i914_answers(self) -> None:
        raw_answers = {
            "p6_1": "B",
            "p6_2": {
                "preparer_statement_selected": True,
            },
            "p7_7": {
                "interpreter_fluent_language": "Spanish",
            },
            "p8_identity": {
                "preparer_business_or_organization_name": "Law Offices of Manuel E. Solis",
            },
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        blocked_fields = {
            (issue["question_id"], issue["field_id"])
            for issue in issues
        }
        self.assertNotIn(("p6_1", "interpreter_language"), blocked_fields)
        self.assertNotIn(("p6_2", "preparer_name_in_statement"), blocked_fields)
        self.assertNotIn(("p7_7", "interpreter_signature"), blocked_fields)
        self.assertNotIn(("p7_7", "interpreter_signature_date"), blocked_fields)
        self.assertNotIn(("p8_identity", "preparer_family_name"), blocked_fields)
        self.assertNotIn(("p8_identity", "preparer_given_name"), blocked_fields)

    def test_validate_form_generation_requirements_does_not_require_online_submission_lea_state_zip(self) -> None:
        raw_answers = {
            "p3_5": "yes",
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        blocked_fields = {
            (issue["question_id"], issue["field_id"])
            for issue in issues
        }
        self.assertNotIn(("p3_5", "lea_agency_office"), blocked_fields)
        self.assertNotIn(("p3_5", "lea_state"), blocked_fields)
        self.assertNotIn(("p3_5", "lea_zip_code"), blocked_fields)

    def test_validate_form_generation_requirements_does_not_require_if_any_passport_fields(self) -> None:
        raw_answers = {
            "p2_passport": {
                "issuing_country": "Honduras",
                "passport_issue_date": "04/15/2021",
                "passport_expiration_date": "04/14/2031",
            }
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(
                issue["question_id"] == "p2_passport"
                and issue["field_id"] == "passport_or_travel_document_number"
                for issue in issues
            )
        )

    def test_validate_form_generation_requirements_defers_i914_recent_arrival_addendum_to_generation(self) -> None:
        raw_answers = {
            "p3_8": "no",
            "p3_8.prior_entry_date": ["08/12/2020"],
            "p3_8.prior_entry_city": ["Laredo"],
            "p3_8.prior_entry_state": ["TX"],
            "p3_8.prior_entry_status": ["B-2"],
            "p3_9": "yes",
            "p3_9.arrival_circumstances": "",
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(issue["question_id"] == "p3_8" and issue["code"] == "missing_required_addendum" for issue in issues)
        )
        self.assertFalse(
            any(
                issue["question_id"] == "p3_9"
                and issue["field_id"] == "arrival_circumstances"
                for issue in issues
            )
        )

    def test_validate_form_generation_requirements_defers_i914_last_entry_completion_to_generation(self) -> None:
        raw_answers = {
            "p3_9": "yes",
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(
                issue["question_id"] == "p2_last_entry"
                and issue["code"] == "missing_required_field"
                for issue in issues
            )
        )

    def test_validate_form_generation_requirements_defers_i914_prior_entries_to_generation(self) -> None:
        raw_answers = {
            "p3_8": "no",
            "p3_9": "yes",
            "p2_last_entry": {
                "last_entry_city": "Laredo",
                "last_entry_state": "TX",
                "last_entry_date": "11/18/2022",
            },
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(
                issue["question_id"] == "p3_8"
                and issue["code"] == "missing_repeatable_entry"
                for issue in issues
            )
        )

    def test_validate_form_generation_requirements_defers_i914_part4_table_to_generation(self) -> None:
        raw_answers = {
            "p4_1b": "yes",
        }

        with (
            patch.object(service, "get_questionnaire_answers", return_value=raw_answers),
            patch.object(service, "_collect_qc_generation_validation_issues", return_value=[]),
        ):
            issues = service.validate_form_generation_requirements(
                SimpleNamespace(),
                "case-1",
                form_type="i-914",
            )

        self.assertFalse(
            any(
                issue["question_id"] == "p4_1_details"
                and issue["code"] == "missing_repeatable_entry"
                for issue in issues
            )
        )

    def test_postprocess_i914_part4_table_completion_fills_known_fields_only(self) -> None:
        targets = [
            {
                "id": "p4_1b_field",
                "questionnaire_item_id": "p4_1b",
                "questionnaire_field_id": "",
            },
            {
                "id": "incident_reason_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_reason",
            },
            {
                "id": "incident_date_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_date",
            },
            {
                "id": "incident_location_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_location",
            },
            {
                "id": "incident_outcome_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_outcome",
            },
        ]
        results_by_id = {
            "p4_1b_field": {"id": "p4_1b_field", "value": "yes", "confidence": "high", "justification": ""},
            "incident_reason_field": {"id": "incident_reason_field", "value": "", "confidence": "low", "justification": ""},
            "incident_date_field": {"id": "incident_date_field", "value": "", "confidence": "low", "justification": ""},
            "incident_location_field": {"id": "incident_location_field", "value": "", "confidence": "low", "justification": ""},
            "incident_outcome_field": {"id": "incident_outcome_field", "value": "", "confidence": "low", "justification": ""},
        }
        evidence_by_id = {
            "p4_1b_field": {
                "evidence": [
                    {
                        "text": "FBI record states the applicant was detained on 11/18/2022 in Laredo, TX.",
                        "source": "FBI",
                        "sourceType": "fbi",
                    }
                ]
            }
        }

        service._postprocess_i914_part4_table_completion(
            targets,
            results_by_id,
            evidence_by_id,
            {"p4_1b": "yes"},
        )

        self.assertEqual(results_by_id["incident_date_field"]["value"], "Nov 18 2022")
        self.assertEqual(results_by_id["incident_location_field"]["value"], "Laredo, TX")
        self.assertEqual(results_by_id["incident_reason_field"]["value"], "Immigration detention")
        self.assertEqual(results_by_id["incident_outcome_field"]["value"], "Processed and released")

    def test_postprocess_i914_part4_table_completion_clears_duplicate_detention_row(self) -> None:
        targets = [
            {
                "id": "p4_1b_field",
                "questionnaire_item_id": "p4_1b",
                "questionnaire_field_id": "",
            },
            {
                "id": "slot0_reason",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_reason",
                "repeatable_slot_index": 0,
            },
            {
                "id": "slot0_date",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_date",
                "repeatable_slot_index": 0,
            },
            {
                "id": "slot0_location",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_location",
                "repeatable_slot_index": 0,
            },
            {
                "id": "slot0_outcome",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_outcome",
                "repeatable_slot_index": 0,
            },
            {
                "id": "slot1_reason",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_reason",
                "repeatable_slot_index": 1,
            },
            {
                "id": "slot1_date",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_date",
                "repeatable_slot_index": 1,
            },
            {
                "id": "slot1_location",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_location",
                "repeatable_slot_index": 1,
            },
            {
                "id": "slot1_outcome",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_outcome",
                "repeatable_slot_index": 1,
            },
        ]
        results_by_id = {
            "p4_1b_field": {"id": "p4_1b_field", "value": "yes", "confidence": "high", "justification": ""},
            "slot0_reason": {"id": "slot0_reason", "value": "", "confidence": "low", "justification": ""},
            "slot0_date": {"id": "slot0_date", "value": "", "confidence": "low", "justification": ""},
            "slot0_location": {"id": "slot0_location", "value": "", "confidence": "low", "justification": ""},
            "slot0_outcome": {"id": "slot0_outcome", "value": "", "confidence": "low", "justification": ""},
            "slot1_reason": {"id": "slot1_reason", "value": "Immigration detention", "confidence": "low", "justification": ""},
            "slot1_date": {"id": "slot1_date", "value": "09/01/1995", "confidence": "low", "justification": ""},
            "slot1_location": {"id": "slot1_location", "value": "Calexico, CA", "confidence": "low", "justification": ""},
            "slot1_outcome": {"id": "slot1_outcome", "value": "Processed and released", "confidence": "low", "justification": ""},
        }
        evidence_by_id = {
            "p4_1b_field": {
                "evidence": [
                    {
                        "text": "CBP records show the applicant was detained on 09/01/1995 in Calexico, CA.",
                        "source": "FBI",
                        "sourceType": "fbi",
                    }
                ]
            }
        }

        service._postprocess_i914_part4_table_completion(
            targets,
            results_by_id,
            evidence_by_id,
            {"p4_1b": "yes"},
        )

        self.assertEqual(results_by_id["slot0_reason"]["value"], "Immigration detention")
        self.assertEqual(results_by_id["slot0_date"]["value"], "Sep 01 1995")
        self.assertEqual(results_by_id["slot0_location"]["value"], "Calexico, CA")
        self.assertEqual(results_by_id["slot0_outcome"]["value"], "Processed and released")
        self.assertEqual(results_by_id["slot1_reason"]["value"], "")
        self.assertEqual(results_by_id["slot1_date"]["value"], "")
        self.assertEqual(results_by_id["slot1_location"]["value"], "")
        self.assertEqual(results_by_id["slot1_outcome"]["value"], "")

    def test_postprocess_i914_part4_table_completion_prefers_saved_last_entry_over_noisy_evidence(self) -> None:
        targets = [
            {
                "id": "p4_1b_yes_field",
                "questionnaire_item_id": "p4_1b",
                "questionnaire_field_id": "",
                "questionnaire_option_value": "yes",
            },
            {
                "id": "incident_date_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_date",
            },
            {
                "id": "incident_location_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_location",
            },
            {
                "id": "incident_reason_field",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_reason",
            },
        ]
        results_by_id = {
            "p4_1b_yes_field": {"id": "p4_1b_yes_field", "value": "yes", "confidence": "high", "justification": ""},
            "incident_date_field": {"id": "incident_date_field", "value": "", "confidence": "low", "justification": ""},
            "incident_location_field": {"id": "incident_location_field", "value": "", "confidence": "low", "justification": ""},
            "incident_reason_field": {"id": "incident_reason_field", "value": "", "confidence": "low", "justification": ""},
        }
        evidence_by_id = {}

        service._postprocess_i914_part4_table_completion(
            targets,
            results_by_id,
            evidence_by_id,
            {
                "p4_1b": "yes",
                "p2_last_entry": {
                    "last_entry_city": "Laredo",
                    "last_entry_state": "TX",
                    "last_entry_date": "11/18/2022",
                },
            },
            detention_facts={
                "date": "11/18/2022",
                "location": "Bolivia",
                "location_city": "Bolivia",
                "reason": "Pregunta: Item 32 - Date of entry to the United States Respuesta: November 2022",
            },
        )

        self.assertEqual(results_by_id["incident_date_field"]["value"], "Nov 18 2022")
        self.assertEqual(results_by_id["incident_location_field"]["value"], "Laredo, TX")
        self.assertTrue(results_by_id["incident_reason_field"]["value"])

    def test_collect_i914_result_review_issues_does_not_flag_conflicts(self) -> None:
        issues = service._collect_i914_result_review_issues(
            [
                {
                    "id": "p4_1b_field",
                    "questionnaire_item_id": "p4_1b",
                    "questionnaire_field_id": "",
                }
            ],
            {
                "p4_1b_field": {
                    "id": "p4_1b_field",
                    "value": "no",
                    "confidence": "low",
                    "justification": "CONFLICT: FBI record shows a detention event.",
                }
            },
            {},
        )

        self.assertFalse(any("Higher-tier evidence conflicts" in issue for issue in issues))

    def test_collect_i914_result_review_issues_does_not_flag_missing_arrival_narrative(self) -> None:
        issues = service._collect_i914_result_review_issues(
            [
                {
                    "id": "last_entry_date_field",
                    "questionnaire_item_id": "p2_last_entry",
                    "questionnaire_field_id": "last_entry_date",
                },
                {
                    "id": "last_entry_city_field",
                    "questionnaire_item_id": "p2_last_entry",
                    "questionnaire_field_id": "last_entry_city",
                },
                {
                    "id": "last_entry_state_field",
                    "questionnaire_item_id": "p2_last_entry",
                    "questionnaire_field_id": "last_entry_state",
                },
            ],
            {
                "last_entry_date_field": {"id": "last_entry_date_field", "value": "11/18/2022"},
                "last_entry_city_field": {"id": "last_entry_city_field", "value": "Laredo"},
                "last_entry_state_field": {"id": "last_entry_state_field", "value": "TX"},
            },
            {
                "p3_9": "yes",
                "p2_last_entry": {
                    "last_entry_date": "11/18/2022",
                    "last_entry_city": "Laredo",
                    "last_entry_state": "TX",
                },
            },
        )

        self.assertFalse(any("arrival narrative" in issue for issue in issues))

    def test_postprocess_i914_part4_consistency_ignores_no_widgets_when_any_question_is_yes(self) -> None:
        targets = [
            {
                "id": "p4_1a_no_field",
                "questionnaire_item_id": "p4_1a",
                "questionnaire_field_id": "",
                "questionnaire_option_value": "no",
            },
            {
                "id": "p4_1b_yes_field",
                "questionnaire_item_id": "p4_1b",
                "questionnaire_field_id": "",
                "questionnaire_option_value": "yes",
            },
            {
                "id": "p4_1b_no_field",
                "questionnaire_item_id": "p4_1b",
                "questionnaire_field_id": "",
                "questionnaire_option_value": "no",
            },
        ]
        results_by_id = {
            "p4_1a_no_field": {
                "id": "p4_1a_no_field",
                "value": "yes",
                "confidence": "high",
                "justification": "Saved questionnaire answer from p4_1a.",
            },
            "p4_1b_yes_field": {
                "id": "p4_1b_yes_field",
                "value": "yes",
                "confidence": "high",
                "justification": "Saved questionnaire answer from p4_1b.",
            },
            "p4_1b_no_field": {
                "id": "p4_1b_no_field",
                "value": "off",
                "confidence": "high",
                "justification": "Saved questionnaire answer from p4_1b.",
            },
        }

        service._postprocess_i914_part4_consistency(
            targets,
            results_by_id,
            {},
            detention_facts={"date": "11/18/2022", "location": "Laredo, TX", "source_tier": "1"},
        )

        self.assertNotIn("CONFLICT:", results_by_id["p4_1b_no_field"]["justification"])

    def test_collect_qc_generation_validation_issues_blocks_fbi_correction(self) -> None:
        class _FakeQcQuery:
            def __init__(self, rows) -> None:
                self._rows = rows

            def join(self, *args, **kwargs):
                return self

            def filter(self, *args, **kwargs):
                return self

            def all(self):
                return self._rows

        class _FakeQcDb:
            def __init__(self, rows) -> None:
                self._rows = rows

            def query(self, *models):
                return _FakeQcQuery(self._rows)

        fake_db = _FakeQcDb(
            [
                (
                    SimpleNamespace(
                        name="QC Checklist – I-914 (T-1)",
                        description="Quality Control checklist for I-914",
                    ),
                    SimpleNamespace(
                        code="4.1.B",
                        description="Arrest review",
                        correction="FBI record shows a prior arrest that is not reflected in the form.",
                        answer="no",
                        where_to_verify="FBI; Declaration",
                    ),
                )
            ]
        )

        issues = service._collect_qc_generation_validation_issues(
            fake_db,
            case_id="case-1",
            form_type="i-914",
            known_codes={"4.1.B"},
        )

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "qc_correction_pending")
        self.assertIn("FBI", issues[0]["message"])

    def test_field_rows_need_unit_type_repair_uses_precomputed_targets_and_results(self) -> None:
        field_rows = [
            SimpleNamespace(
                field_name="unit_type_apt",
                manually_corrected=False,
                extracted_value="off",
            )
        ]
        targets = [
            {
                "field_name": "unit_type_apt",
                "field_type": "checkbox",
                "field_label": "Check this box for Apartment",
                "page_number": 1,
            }
        ]
        results_by_id = {
            "unit_type_apt": {
                "id": "unit_type_apt",
                "value": "yes",
                "confidence": "high",
                "justification": "Precomputed expected value.",
            }
        }
        answers = {"shared.current_physical_address": {"unit_type": "Apt."}}

        with (
            patch.object(service, "map_pdf_fields_to_questionnaire_ids") as mapping_mock,
            patch.object(service, "_build_extraction_targets") as targets_mock,
            patch.object(service, "_build_results_from_answers") as results_mock,
        ):
            needs_repair = service._field_rows_need_unit_type_repair(
                field_rows,
                resolved_form_type="i-914",
                pdf_fields=[{"field_name": "unit_type_apt"}],
                answers=answers,
                precomputed_targets=targets,
                precomputed_results_by_id=results_by_id,
            )

        self.assertTrue(needs_repair)
        mapping_mock.assert_not_called()
        targets_mock.assert_not_called()
        results_mock.assert_not_called()


    def test_shared_answer_candidates_generates_unit_type_for_apt_ste_flr_label(self) -> None:
        target = {
            "field_name": "P2_Line3_AptSteFlr[0]",
            "field_label": "Apt. Ste. Flr.",
            "field_type": "checkbox",
            "canonical_questionnaire_id": None,
            "questionnaire_item_id": None,
            "questionnaire_field_id": None,
            "questionnaire_label": "Apt./Ste./Flr.",
            "questionnaire_form_text": "Physical Address",
            "questionnaire_section": "Part 2. General Information About You",
            "questionnaire_option_label": None,
        }

        candidates = service._shared_answer_candidates(target, 0)
        question_ids = [c[0] for c in candidates]

        self.assertTrue(
            any("unit_type" in qid for qid in question_ids),
            f"Expected at least one candidate with 'unit_type', got: {question_ids}",
        )

    def test_shared_answer_candidates_unit_number_still_works(self) -> None:
        target = {
            "field_name": "P2_Line3_Number[0]",
            "field_label": "Apartment, Suite, or Floor Number",
            "field_type": "text",
            "canonical_questionnaire_id": None,
            "questionnaire_item_id": None,
            "questionnaire_field_id": None,
            "questionnaire_label": None,
            "questionnaire_form_text": "Physical Address",
            "questionnaire_section": "Part 2. General Information About You",
            "questionnaire_option_label": None,
        }

        candidates = service._shared_answer_candidates(target, 0)
        question_ids = [c[0] for c in candidates]

        self.assertTrue(
            any("unit_number" in qid for qid in question_ids),
            f"Expected at least one candidate with 'unit_number', got: {question_ids}",
        )

    def test_collect_evidence_for_targets_sync_uses_form_document_scope(self) -> None:
        targets = [
            {
                "id": "field-1",
                "search_query": "passport number",
                "field_label": "Passport Number",
                "questionnaire_where_to_verify": "Passport",
            }
        ]
        settings = SimpleNamespace(
            embedding_task_type_query="retrieval-query",
            autopilot_evidence_top_k=6,
            autopilot_evidence_max_chars=12000,
            autopilot_evidence_workers=1,
        )

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "get_embedding_batch", return_value=[[0.1, 0.2]]),
            patch.object(
                service,
                "collect_evidence_bundle_for_question",
                return_value={
                    "evidence": [],
                    "text_context": "",
                    "source_pages": [],
                    "stage": "source_document",
                    "matches": [],
                },
            ) as collect_mock,
        ):
            result = service._collect_evidence_for_targets_sync(
                targets,
                case_id="case-1",
                tracker=SimpleNamespace(),
                source_document_ids=["doc-1", "doc-2"],
            )

        self.assertIn("field-1", result)
        self.assertEqual(collect_mock.call_count, 1)
        self.assertEqual(
            collect_mock.call_args.kwargs["source_document_ids"],
            ["doc-1", "doc-2"],
        )
        self.assertFalse(collect_mock.call_args.kwargs["document_fallback_enabled"])

    def test_collect_evidence_for_targets_uses_form_document_scope(self) -> None:
        targets = [
            {
                "id": "field-1",
                "search_query": "passport expiration date",
                "field_label": "Passport Expiration Date",
                "questionnaire_where_to_verify": "Passport",
            }
        ]
        settings = SimpleNamespace(
            embedding_task_type_query="retrieval-query",
            autopilot_evidence_top_k=6,
            autopilot_evidence_max_chars=12000,
            autopilot_evidence_workers=1,
        )

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "get_embedding_batch", return_value=[[0.3, 0.4]]),
            patch.object(service.form_filling_jobs, "update_evidence_progress"),
            patch.object(
                service,
                "collect_evidence_bundle_for_question",
                return_value={
                    "evidence": [],
                    "text_context": "",
                    "source_pages": [],
                    "stage": "source_document",
                    "matches": [],
                },
            ) as collect_mock,
        ):
            result = service._collect_evidence_for_targets(
                targets,
                case_id="case-1",
                job_id="job-1",
                tracker=SimpleNamespace(),
                source_document_ids=["doc-9"],
            )

        self.assertIn("field-1", result)
        self.assertEqual(collect_mock.call_count, 1)
        self.assertEqual(
            collect_mock.call_args.kwargs["source_document_ids"],
            ["doc-9"],
        )
        self.assertFalse(collect_mock.call_args.kwargs["document_fallback_enabled"])

    def test_extract_values_for_targets_discards_checkbox_artifact_value(self) -> None:
        targets = [
            {
                "id": "checkbox_field",
                "field_name": "checkbox_field",
                "field_label": "Check here",
                "field_type": "checkbox",
                "page_number": 1,
                "canonical_questionnaire_id": "q1",
                "questionnaire_item_id": "q1",
                "questionnaire_field_id": None,
                "question_id": "q1",
                "answer_field_id": None,
                "questionnaire_item_type": "checkbox",
                "questionnaire_options": [],
            }
        ]
        evidence_by_id = {
            "checkbox_field": {
                "text_context": "Nearby scanned mark: x",
            }
        }
        settings = SimpleNamespace(autopilot_batch_size=10)

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(
                service,
                "extract_field_values_batch",
                return_value=[
                    {
                        "id": "checkbox_field",
                        "value": "x",
                        "confidence": "high",
                        "justification": "Nearby mark.",
                    }
                ],
            ),
            patch.object(service.form_filling_jobs, "update_extraction_progress"),
        ):
            results_by_id, filled_count, extraction_error_count = service._extract_values_for_targets(
                targets,
                evidence_by_id=evidence_by_id,
                form_type="i-914",
                job_id="job-1",
                tracker=SimpleNamespace(),
            )

        self.assertEqual(extraction_error_count, 0)
        self.assertEqual(filled_count, 0)
        self.assertEqual(results_by_id["checkbox_field"]["value"], "")
        self.assertEqual(results_by_id["checkbox_field"]["confidence"], "low")
        self.assertIn(
            "unsupported artifact",
            results_by_id["checkbox_field"]["justification"],
        )

    def test_extract_values_for_targets_sync_skips_lea_unit_number_field(self) -> None:
        targets = [
            {
                "id": "p3_5.lea_unit_number",
                "field_name": "p3_5.lea_unit_number",
                "field_label": "Number",
                "field_type": "text",
                "page_number": 3,
                "canonical_questionnaire_id": "p3_5.lea_unit_number",
                "questionnaire_item_id": "p3_5",
                "questionnaire_field_id": "lea_unit_number",
                "question_id": "p3_5",
                "answer_field_id": "lea_unit_number",
                "questionnaire_item_type": "text",
                "questionnaire_options": [],
            }
        ]
        settings = SimpleNamespace(autopilot_batch_size=10)

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "extract_field_values_batch") as batch_mock,
        ):
            results_by_id, extraction_error_count, error_breakdown = service._extract_values_for_targets_sync(
                targets,
                evidence_by_id={},
                form_type="i-914",
                tracker=SimpleNamespace(),
            )

        self.assertEqual(extraction_error_count, 0)
        self.assertEqual(error_breakdown, {})
        batch_mock.assert_not_called()
        self.assertEqual(results_by_id["p3_5.lea_unit_number"]["value"], "")
        self.assertEqual(results_by_id["p3_5.lea_unit_number"]["confidence"], "low")
        self.assertIn(
            "intentionally left blank",
            results_by_id["p3_5.lea_unit_number"]["justification"],
        )

    def test_anthropic_questionnaire_autofill_skips_batch_and_uses_single_extraction(self) -> None:
        targets = [
            {
                "id": "field_1",
                "field_name": "field_1",
                "field_label": "Field 1",
                "field_type": "text",
                "page_number": 1,
                "canonical_questionnaire_id": "q1",
                "questionnaire_item_id": "q1",
                "questionnaire_field_id": None,
                "question_id": "q1",
                "answer_field_id": None,
                "questionnaire_item_type": "text",
                "questionnaire_options": [],
            },
            {
                "id": "field_2",
                "field_name": "field_2",
                "field_label": "Field 2",
                "field_type": "text",
                "page_number": 1,
                "canonical_questionnaire_id": "q2",
                "questionnaire_item_id": "q2",
                "questionnaire_field_id": None,
                "question_id": "q2",
                "answer_field_id": None,
                "questionnaire_item_type": "text",
                "questionnaire_options": [],
            },
        ]
        settings = SimpleNamespace(
            autopilot_batch_size=10,
            autopilot_llm_batch_concurrency=2,
            extraction_provider="anthropic",
        )

        def extract_single(field, evidence, **_kwargs):
            return {
                "value": f"value for {field['id']}",
                "confidence": "high",
                "justification": str(evidence),
            }

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "extract_field_values_batch") as batch_mock,
            patch.object(service, "extract_field_value", side_effect=extract_single) as single_mock,
        ):
            results_by_id, extraction_error_count, error_breakdown = service._extract_values_for_targets_sync(
                targets,
                evidence_by_id={"field_1": "Evidence 1", "field_2": "Evidence 2"},
                form_type="i-914",
                tracker=SimpleNamespace(),
            )

        self.assertEqual(extraction_error_count, 0)
        self.assertEqual(error_breakdown, {})
        batch_mock.assert_not_called()
        self.assertEqual(single_mock.call_count, 2)
        self.assertEqual(results_by_id["field_1"]["value"], "value for field_1")
        self.assertEqual(results_by_id["field_2"]["value"], "value for field_2")

    def test_extraction_circuit_breaker_aborts_when_same_error_dominates_first_ten_fields(self) -> None:
        class ProviderOutage(RuntimeError):
            pass

        targets = [_minimal_autofill_target(f"field_{index}") for index in range(1, 11)]
        settings = SimpleNamespace(
            autopilot_batch_size=10,
            autopilot_llm_batch_concurrency=1,
            extraction_provider="anthropic",
        )
        errors = [ProviderOutage("provider unavailable") for _ in range(8)]
        errors.extend(ValueError("isolated parse issue") for _ in range(2))

        with (
            patch.object(service, "get_rag_settings", return_value=settings),
            patch.object(service, "_extraction_circuit_breaker_enabled", return_value=True),
            patch.object(service, "extract_field_value", side_effect=errors) as single_mock,
        ):
            with self.assertRaises(service.ExtractionCircuitBreakerOpen) as ctx:
                service._extract_values_for_targets_sync(
                    targets,
                    evidence_by_id={target["id"]: f"Evidence {target['id']}" for target in targets},
                    form_type="i-914",
                    tracker=SimpleNamespace(),
                )

        self.assertEqual(single_mock.call_count, 10)
        self.assertEqual(ctx.exception.exc_type, "ProviderOutage")
        self.assertEqual(ctx.exception.error_count, 8)
        self.assertEqual(ctx.exception.processed_count, 10)
        self.assertEqual(ctx.exception.total_targets, 10)

    def test_normalize_address_field_id_strips_entry_and_lea_prefixes(self) -> None:
        self.assertEqual(service._normalize_address_field_id("last_entry_state"), "state")
        self.assertEqual(service._normalize_address_field_id("last_entry_city"), "city")
        self.assertEqual(service._normalize_address_field_id("prior_entry_state"), "state")
        self.assertEqual(service._normalize_address_field_id("prior_entry_city"), "city")
        self.assertEqual(service._normalize_address_field_id("lea_state"), "state")
        self.assertEqual(service._normalize_address_field_id("lea_city"), "city")
        self.assertEqual(service._normalize_address_field_id("lea_zip_code"), "zip_code")
        self.assertEqual(service._normalize_address_field_id("safe_state"), "state")
        self.assertEqual(service._normalize_address_field_id("state"), "state")

    def test_infer_state_from_city_returns_code_for_known_cities(self) -> None:
        self.assertEqual(service._infer_state_from_city("Laredo"), "TX")
        self.assertEqual(service._infer_state_from_city("laredo"), "TX")
        self.assertEqual(service._infer_state_from_city("LAREDO"), "TX")
        self.assertEqual(service._infer_state_from_city("El Paso"), "TX")
        self.assertEqual(service._infer_state_from_city("Brownsville"), "TX")
        self.assertEqual(service._infer_state_from_city("Miami"), "FL")
        self.assertEqual(service._infer_state_from_city("San Ysidro"), "CA")
        self.assertEqual(service._infer_state_from_city("Nogales"), "AZ")
        self.assertEqual(service._infer_state_from_city("Buffalo"), "NY")
        self.assertEqual(service._infer_state_from_city("Detroit"), "MI")
        self.assertEqual(service._infer_state_from_city("  Laredo  "), "TX")

    def test_infer_state_from_city_handles_entry_aliases(self) -> None:
        self.assertEqual(service._infer_state_from_city("Port of Entry: Laredo"), "TX")
        self.assertEqual(service._infer_state_from_city("Place of Entry - City or Town: San Ysidro"), "CA")
        self.assertEqual(service._infer_state_from_city("Laredo, TX"), "TX")

    def test_infer_state_from_city_returns_empty_for_ambiguous_city(self) -> None:
        self.assertEqual(service._infer_state_from_city("Portland"), "")
        self.assertEqual(service._infer_state_from_city("Washington"), "")

    def test_infer_state_from_city_returns_empty_for_unknown(self) -> None:
        self.assertEqual(service._infer_state_from_city(""), "")
        self.assertEqual(service._infer_state_from_city("Unknown City XYZ"), "")
        self.assertEqual(service._infer_state_from_city(None), "")

    def test_postprocess_address_results_infers_state_from_city_for_entry_fields(self) -> None:
        targets = [
            {
                "id": "p2_last_entry.last_entry_city",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
            },
            {
                "id": "p2_last_entry.last_entry_state",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
            },
        ]
        results_by_id: dict[str, dict[str, str]] = {
            "p2_last_entry.last_entry_city": {
                "id": "p2_last_entry.last_entry_city",
                "value": "Laredo",
                "confidence": "high",
                "justification": "Found in I-94.",
            },
            "p2_last_entry.last_entry_state": {
                "id": "p2_last_entry.last_entry_state",
                "value": "",
                "confidence": "low",
                "justification": "",
            },
        }

        service._postprocess_address_results(targets, results_by_id, {})

        self.assertEqual(
            results_by_id["p2_last_entry.last_entry_state"]["value"],
            "TX",
        )

    def test_postprocess_address_results_clears_partial_last_entry_location_when_state_cannot_be_inferred(self) -> None:
        targets = [
            {
                "id": "p2_last_entry.last_entry_city",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_label": "Place of Your Last Entry Into the United States - City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
            },
            {
                "id": "p2_last_entry.last_entry_state",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_label": "Place of Your Last Entry Into the United States - State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
            },
            {
                "id": "p2_last_entry.last_entry_zip_code",
                "question_id": "p2_last_entry",
                "answer_field_id": "zip_code",
                "questionnaire_field_id": "zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2. General Information About You",
            },
        ]
        results_by_id = {
            "p2_last_entry.last_entry_state": {
                "id": "p2_last_entry.last_entry_state",
                "value": "",
                "confidence": "low",
                "justification": "",
            },
            "p2_last_entry.last_entry_zip_code": {
                "id": "p2_last_entry.last_entry_zip_code",
                "value": "11377",
                "confidence": "high",
                "justification": "Found in evidence.",
            },
        }

        service._postprocess_address_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["p2_last_entry.last_entry_city"]["value"], "")
        self.assertEqual(results_by_id["p2_last_entry.last_entry_state"]["value"], "")
        self.assertEqual(results_by_id["p2_last_entry.last_entry_city"]["confidence"], "low")
        self.assertIn(
            "requires both city and state",
            results_by_id["p2_last_entry.last_entry_city"]["justification"],
        )

    def test_postprocess_address_results_does_not_overwrite_existing_state(self) -> None:
        targets = [
            {
                "id": "p2_last_entry.last_entry_city",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2",
            },
            {
                "id": "p2_last_entry.last_entry_state",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2",
            },
        ]
        results_by_id: dict[str, dict[str, str]] = {
            "p2_last_entry.last_entry_city": {
                "id": "p2_last_entry.last_entry_city",
                "value": "Laredo",
                "confidence": "high",
                "justification": "",
            },
            "p2_last_entry.last_entry_state": {
                "id": "p2_last_entry.last_entry_state",
                "value": "CA",
                "confidence": "high",
                "justification": "Explicitly stated.",
            },
        }

        service._postprocess_address_results(targets, results_by_id, {})

        self.assertEqual(
            results_by_id["p2_last_entry.last_entry_state"]["value"],
            "CA",
        )

    def test_postprocess_address_results_corrects_existing_state_with_zip_evidence(self) -> None:
        targets = [
            {
                "id": "p2_last_entry.last_entry_city",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_city",
                "questionnaire_field_id": "last_entry_city",
                "field_label": "City or Town",
                "questionnaire_label": "City or Town",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2",
            },
            {
                "id": "p2_last_entry.last_entry_state",
                "question_id": "p2_last_entry",
                "answer_field_id": "last_entry_state",
                "questionnaire_field_id": "last_entry_state",
                "field_label": "State",
                "questionnaire_label": "State",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2",
            },
            {
                "id": "p2_last_entry.zip_code",
                "question_id": "p2_last_entry",
                "answer_field_id": "zip_code",
                "questionnaire_field_id": "zip_code",
                "field_label": "ZIP Code",
                "questionnaire_label": "ZIP Code",
                "questionnaire_form_text": "Last Entry Into the United States",
                "questionnaire_section": "Part 2",
            },
        ]
        results_by_id = {
            "p2_last_entry.last_entry_city": {
                "id": "p2_last_entry.last_entry_city",
                "value": "Laredo",
                "confidence": "high",
                "justification": "",
            },
            "p2_last_entry.last_entry_state": {
                "id": "p2_last_entry.last_entry_state",
                "value": "CA",
                "confidence": "high",
                "justification": "Model guessed incorrectly.",
            },
            "p2_last_entry.zip_code": {
                "id": "p2_last_entry.zip_code",
                "value": "78040",
                "confidence": "high",
                "justification": "Found in evidence.",
            },
        }

        service._postprocess_address_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["p2_last_entry.last_entry_state"]["value"], "TX")

    def test_postprocess_address_results_handles_repeatable_prior_entry_rows_independently(self) -> None:
        targets = [
            {
                "id": "p3_8.prior_entry_city[0]",
                "question_id": "p3_8",
                "answer_field_id": "prior_entry_city",
                "questionnaire_field_id": "prior_entry_city",
                "questionnaire_form_text": "This is the first time I have entered the United States.",
                "questionnaire_section": "Part 3",
                "occurrence_index": 0,
            },
            {
                "id": "p3_8.prior_entry_state[0]",
                "question_id": "p3_8",
                "answer_field_id": "prior_entry_state",
                "questionnaire_field_id": "prior_entry_state",
                "questionnaire_form_text": "This is the first time I have entered the United States.",
                "questionnaire_section": "Part 3",
                "occurrence_index": 0,
            },
            {
                "id": "p3_8.prior_entry_city[1]",
                "question_id": "p3_8",
                "answer_field_id": "prior_entry_city",
                "questionnaire_field_id": "prior_entry_city",
                "questionnaire_form_text": "This is the first time I have entered the United States.",
                "questionnaire_section": "Part 3",
                "occurrence_index": 1,
            },
            {
                "id": "p3_8.prior_entry_state[1]",
                "question_id": "p3_8",
                "answer_field_id": "prior_entry_state",
                "questionnaire_field_id": "prior_entry_state",
                "questionnaire_form_text": "This is the first time I have entered the United States.",
                "questionnaire_section": "Part 3",
                "occurrence_index": 1,
            },
        ]
        results_by_id = {
            "p3_8.prior_entry_city[0]": {
                "id": "p3_8.prior_entry_city[0]",
                "value": "Laredo",
                "confidence": "high",
                "justification": "",
            },
            "p3_8.prior_entry_state[0]": {
                "id": "p3_8.prior_entry_state[0]",
                "value": "",
                "confidence": "low",
                "justification": "",
            },
            "p3_8.prior_entry_city[1]": {
                "id": "p3_8.prior_entry_city[1]",
                "value": "San Ysidro",
                "confidence": "high",
                "justification": "",
            },
            "p3_8.prior_entry_state[1]": {
                "id": "p3_8.prior_entry_state[1]",
                "value": "",
                "confidence": "low",
                "justification": "",
            },
        }

        service._postprocess_address_results(targets, results_by_id, {})

        self.assertEqual(results_by_id["p3_8.prior_entry_state[0]"]["value"], "TX")
        self.assertEqual(results_by_id["p3_8.prior_entry_state[1]"]["value"], "CA")


class FormFillingPromptsTests(unittest.TestCase):
    def test_expected_output_hint_fires_for_entry_state_field(self) -> None:
        from app.prompts.form_filling_prompts import _expected_output_hint

        field = {
            "id": "p2_last_entry.last_entry_state",
            "field_name": "last_entry_state",
            "field_label": "Place of Your Last Entry Into the United States - State",
            "field_type": "select",
            "questionnaire_field_id": "last_entry_state",
            "questionnaire_label": "Place of Your Last Entry Into the United States - State",
            "questionnaire_form_text": "Last Entry Into the United States",
            "questionnaire_section": "Part 2. General Information About You",
        }
        hint = _expected_output_hint(field)
        self.assertIn("USPS", hint)
        self.assertIn("2 letras", hint)

    def test_expected_output_hint_fires_for_lea_state_field(self) -> None:
        from app.prompts.form_filling_prompts import _expected_output_hint

        field = {
            "id": "lea.lea_state",
            "field_name": "lea_state",
            "field_label": "State",
            "field_type": "select",
            "questionnaire_field_id": "lea_state",
            "questionnaire_label": "State",
            "questionnaire_form_text": "Law Enforcement Agency",
            "questionnaire_section": "Part 3",
        }
        hint = _expected_output_hint(field)
        self.assertIn("USPS", hint)

    def test_expected_output_hint_still_fires_for_address_state_field(self) -> None:
        from app.prompts.form_filling_prompts import _expected_output_hint

        field = {
            "id": "shared.current_physical_address.state",
            "field_name": "state",
            "field_label": "State",
            "field_type": "select",
            "questionnaire_field_id": "state",
            "questionnaire_label": "State",
            "questionnaire_form_text": "Current Physical Address",
            "questionnaire_section": "Address Information",
        }
        hint = _expected_output_hint(field)
        self.assertIn("USPS", hint)
        self.assertIn("2 letras", hint)


class I914FamilyExtractionPromptTests(unittest.TestCase):
    def test_system_prompt_contains_applicant_and_schema(self) -> None:
        from app.prompts.form_filling_prompts import (
            build_i914_family_extraction_system_prompt,
        )

        prompt = build_i914_family_extraction_system_prompt("Natalia Reyes Gonzalez")
        self.assertIn("Natalia Reyes Gonzalez", prompt)
        self.assertIn('"spouse"', prompt)
        self.assertIn('"children"', prompt)
        self.assertIn("Mmm DD YYYY", prompt)
        self.assertIn("TODOS", prompt)

    def test_system_prompt_handles_empty_applicant(self) -> None:
        from app.prompts.form_filling_prompts import (
            build_i914_family_extraction_system_prompt,
        )

        prompt = build_i914_family_extraction_system_prompt("")
        self.assertIn("peticion I-914", prompt)
        self.assertIn('"spouse"', prompt)

    def test_request_prompt_embeds_evidence_and_applicant(self) -> None:
        from app.prompts.form_filling_prompts import (
            build_i914_family_extraction_request_prompt,
        )

        payload = build_i914_family_extraction_request_prompt(
            evidence_text="Spouse: John Doe, DOB 01/01/1990.",
            applicant_name="Jane Smith",
        )
        self.assertIn("Jane Smith", payload)
        self.assertIn("Spouse: John Doe", payload)


class I914FamilyMemberNormalizationTests(unittest.TestCase):
    def test_normalize_spouse_maps_to_spouse_field_ids(self) -> None:
        record = service._normalize_family_person_record(
            {
                "family_name": "Perez",
                "given_name": "Carlos",
                "middle_name": "Alberto",
                "date_of_birth": "1985-06-15",
                "country_of_birth": "Mexico",
                "residence_city": "Mexico City",
                "residence_country": "Mexico",
            },
            is_child=False,
        )
        self.assertEqual(record["spouse_family_name"], "Perez")
        self.assertEqual(record["spouse_given_name"], "Carlos")
        self.assertEqual(record["spouse_middle_name"], "Alberto")
        self.assertEqual(record["spouse_date_of_birth"], "06/15/1985")
        self.assertEqual(record["spouse_country_of_birth"], "Mexico")
        self.assertEqual(record["spouse_residence_city"], "Mexico City")
        self.assertEqual(record["spouse_residence_country"], "Mexico")

    def test_normalize_child_maps_to_child_field_ids(self) -> None:
        record = service._normalize_family_person_record(
            {
                "family_name": "Reyes Gonzalez",
                "given_name": "Maria",
                "middle_name": "",
                "date_of_birth": "03/04/2010",
                "country_of_birth": "Mexico",
                "current_city": "Houston",
                "current_state": "Texas",
                "current_country": "United States",
            },
            is_child=True,
        )
        self.assertEqual(record["family_name"], "Reyes Gonzalez")
        self.assertEqual(record["given_name"], "Maria")
        self.assertEqual(record["date_of_birth"], "03/04/2010")
        self.assertEqual(record["current_state"], "TX")
        self.assertEqual(record["current_city"], "Houston")
        self.assertEqual(record["current_country"], "United States")

    def test_normalize_splits_compound_hispanic_given_name(self) -> None:
        record = service._normalize_family_person_record(
            {
                "family_name": "Reyes Gonzalez",
                "given_name": "Natalia Hilda",
                "middle_name": "",
                "date_of_birth": "01/02/1980",
                "country_of_birth": "Mexico",
                "current_city": "Mexico City",
                "current_state": "",
                "current_country": "Mexico",
            },
            is_child=True,
        )
        self.assertEqual(record["given_name"], "Natalia")
        self.assertEqual(record["middle_name"], "Hilda")
        self.assertEqual(record["family_name"], "Reyes Gonzalez")

    def test_normalize_returns_empty_when_no_name_present(self) -> None:
        record = service._normalize_family_person_record(
            {
                "family_name": "",
                "given_name": "",
                "date_of_birth": "01/01/1990",
            },
            is_child=False,
        )
        self.assertEqual(record, {})

    def test_normalize_returns_empty_on_none(self) -> None:
        self.assertEqual(service._normalize_family_person_record(None, is_child=True), {})

    def test_dedupe_children_removes_duplicates(self) -> None:
        children = [
            {"given_name": "Maria", "middle_name": "", "family_name": "Reyes", "date_of_birth": "01/01/2010"},
            {"given_name": "maria", "middle_name": "", "family_name": "reyes", "date_of_birth": "01/01/2010"},
            {"given_name": "Jose", "middle_name": "", "family_name": "Reyes", "date_of_birth": "02/02/2012"},
        ]
        deduped = service._dedupe_family_children(children)
        self.assertEqual(len(deduped), 2)


class I914FamilyMembersExtractorTests(unittest.TestCase):
    def _fake_bundle(self, text: str = "Spouse: John Doe. Child: Maria Doe.") -> dict:
        return {
            "evidence": [],
            "text_context": text,
            "source_pages": [],
            "stage": "ok",
            "matches": [],
        }

    def test_extractor_returns_normalized_spouse_and_children(self) -> None:
        bundle = self._fake_bundle()
        raw_response = {
            "spouse": {
                "family_name": "Doe",
                "given_name": "John",
                "middle_name": "",
                "date_of_birth": "1985-01-02",
                "country_of_birth": "Mexico",
                "residence_city": "Guadalajara",
                "residence_country": "Mexico",
            },
            "children": [
                {
                    "family_name": "Doe",
                    "given_name": "Maria",
                    "middle_name": "",
                    "date_of_birth": "05/06/2010",
                    "country_of_birth": "Mexico",
                    "current_city": "Houston",
                    "current_state": "TX",
                    "current_country": "United States",
                },
                {
                    "family_name": "Doe",
                    "given_name": "Luis",
                    "middle_name": "",
                    "date_of_birth": "09/10/2012",
                    "country_of_birth": "Mexico",
                    "current_city": "Houston",
                    "current_state": "TX",
                    "current_country": "United States",
                },
            ],
        }
        with patch.object(service, "collect_evidence_bundle_for_question", return_value=bundle), \
             patch.object(service, "extract_i914_family_members", return_value=raw_response):
            result = service._extract_i914_family_members(
                db=None, case_id="case-xyz1234", applicant_name="Jane Doe"
            )

        self.assertEqual(result["p5_1"]["spouse_family_name"], "Doe")
        self.assertEqual(result["p5_1"]["spouse_given_name"], "John")
        self.assertEqual(result["p5_1"]["spouse_date_of_birth"], "01/02/1985")
        self.assertEqual(len(result["p5_children"]), 2)
        self.assertEqual(result["p5_children"][0]["given_name"], "Maria")
        self.assertEqual(result["p5_children"][0]["current_state"], "TX")
        self.assertEqual(result["p5_children"][1]["given_name"], "Luis")

    def test_extractor_handles_no_spouse(self) -> None:
        bundle = self._fake_bundle("Only one child Maria.")
        raw_response = {
            "spouse": None,
            "children": [
                {
                    "family_name": "Perez",
                    "given_name": "Maria",
                    "middle_name": "",
                    "date_of_birth": "01/02/2010",
                    "country_of_birth": "Mexico",
                    "current_city": "Mexico City",
                    "current_state": "",
                    "current_country": "Mexico",
                }
            ],
        }
        with patch.object(service, "collect_evidence_bundle_for_question", return_value=bundle), \
             patch.object(service, "extract_i914_family_members", return_value=raw_response):
            result = service._extract_i914_family_members(
                db=None, case_id="case-xyz1234", applicant_name="Jane Doe"
            )

        self.assertEqual(result["p5_1"], {})
        self.assertEqual(len(result["p5_children"]), 1)
        self.assertEqual(result["p5_children"][0]["given_name"], "Maria")

    def test_extractor_returns_empty_on_gemini_failure(self) -> None:
        bundle = self._fake_bundle()
        with patch.object(service, "collect_evidence_bundle_for_question", return_value=bundle), \
             patch.object(service, "extract_i914_family_members", side_effect=RuntimeError("boom")):
            result = service._extract_i914_family_members(
                db=None, case_id="case-xyz1234", applicant_name="Jane Doe"
            )
        self.assertEqual(result, {"p5_1": {}, "p5_children": []})

    def test_extractor_returns_empty_when_evidence_missing(self) -> None:
        empty_bundle = {
            "evidence": [],
            "text_context": "",
            "source_pages": [],
            "stage": "empty",
            "matches": [],
        }
        with patch.object(service, "collect_evidence_bundle_for_question", return_value=empty_bundle):
            result = service._extract_i914_family_members(
                db=None, case_id="case-xyz1234", applicant_name="Jane Doe"
            )
        self.assertEqual(result, {"p5_1": {}, "p5_children": []})


class I914FamilyAnswerRulesRegressionTests(unittest.TestCase):
    def test_complete_spouse_and_children_are_preserved(self) -> None:
        answers = {
            "p5_1": {
                "spouse_family_name": "Doe",
                "spouse_given_name": "John",
                "spouse_date_of_birth": "01/02/1985",
                "spouse_country_of_birth": "Mexico",
                "spouse_residence_city": "Guadalajara",
                "spouse_residence_country": "Mexico",
            },
            "p5_children": [
                {
                    "family_name": "Doe",
                    "given_name": "Maria",
                    "date_of_birth": "05/06/2010",
                    "country_of_birth": "Mexico",
                    "current_city": "Mexico City",
                    "current_country": "Mexico",
                },
                {
                    "family_name": "Doe",
                    "given_name": "Luis",
                    "date_of_birth": "09/10/2012",
                    "country_of_birth": "Mexico",
                    "current_city": "Mexico City",
                    "current_country": "Mexico",
                },
            ],
        }
        result = service._apply_i914_family_answer_rules(answers)
        self.assertIsInstance(result["p5_1"], dict)
        self.assertEqual(result["p5_1"].get("spouse_family_name"), "Doe")
        self.assertEqual(len(result["p5_children"]), 2)

    def test_incomplete_spouse_is_cleared_but_children_survive(self) -> None:
        answers = {
            "p5_1": {
                "spouse_family_name": "Doe",
                "spouse_given_name": "",
            },
            "p5_children": [
                {
                    "family_name": "Doe",
                    "given_name": "Maria",
                    "date_of_birth": "05/06/2010",
                    "country_of_birth": "Mexico",
                    "current_city": "Mexico City",
                    "current_country": "Mexico",
                }
            ],
        }
        result = service._apply_i914_family_answer_rules(answers)
        self.assertEqual(result["p5_1"], {})
        self.assertEqual(len(result["p5_children"]), 1)


def test_field_extraction_failure_logs_warning_with_field_id_and_exception_type(caplog) -> None:
    class FieldProviderError(RuntimeError):
        pass

    targets = [_minimal_autofill_target("field_1"), _minimal_autofill_target("field_2")]
    settings = SimpleNamespace(
        autopilot_batch_size=10,
        autopilot_llm_batch_concurrency=1,
        extraction_provider="anthropic",
    )

    with (
        patch.object(service, "get_rag_settings", return_value=settings),
        patch.object(service, "extract_field_value", side_effect=FieldProviderError("rate limit")),
        caplog.at_level(logging.WARNING, logger="form_filling"),
    ):
        batch_by_id, extraction_error_count, error_breakdown = service._extract_target_batch_with_fallback(
            targets,
            evidence_by_id={target["id"]: f"Evidence {target['id']}" for target in targets},
            form_type="i-914",
            tracker=SimpleNamespace(),
            batch_step_label="batch",
            single_step_label_prefix="single",
            warning_message="Batch failed: %s",
            warning_args=("unused",),
        )

    failure_messages = [
        record.getMessage()
        for record in caplog.records
        if "Field extraction failed" in record.getMessage()
    ]
    assert extraction_error_count == 2
    assert error_breakdown == {"FieldProviderError": 2}
    assert set(batch_by_id) == {"field_1", "field_2"}
    assert len(failure_messages) == 2
    assert any("field_id=field_1" in message for message in failure_messages)
    assert any("field_id=field_2" in message for message in failure_messages)
    assert all("exc_type=FieldProviderError" in message for message in failure_messages)


if __name__ == "__main__":
    unittest.main()
