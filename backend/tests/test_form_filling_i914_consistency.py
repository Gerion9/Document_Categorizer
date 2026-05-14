"""Integration tests for the I-914 category consistency validator and the
Part 4 detail deduper inside ``form_filling_service``.

The tests synthesise ``ClassifiedEvent`` objects and fake question targets
instead of running the full pipeline; this keeps them hermetic and avoids
any DB / Gemini dependency.
"""

import unittest

from app.services import form_filling_service as service
from app.services.i914_event_taxonomy import ClassifiedEvent, EventCategory


def _yes_no_target(field_id: str, question_id: str, option: str) -> dict:
    return {
        "id": field_id,
        "questionnaire_item_id": question_id,
        "questionnaire_field_id": question_id,
        "questionnaire_target_option": option,
        "questionnaire_option_value": option,
    }


def _detail_target(field_id: str, field_key: str, row_index: int = 0) -> dict:
    return {
        "id": field_id,
        "questionnaire_item_id": "p4_1_details",
        "questionnaire_field_id": field_key,
        "questionnaire_row_index": row_index,
    }


def _result(value: str, confidence: str = "medium") -> dict:
    return {"value": value, "confidence": confidence, "justification": ""}


class ValidateI914CategoryConsistencyTests(unittest.TestCase):
    def test_nta_in_table_with_p4_9b_no_flags_review(self) -> None:
        targets = [
            _yes_no_target("f-9b-yes", "p4_9b", "yes"),
            _yes_no_target("f-9b-no", "p4_9b", "no"),
            _detail_target("f-reason-0", "incident_reason", row_index=0),
            _detail_target("f-outcome-0", "incident_outcome", row_index=0),
        ]
        results_by_id = {
            "f-9b-yes": _result(""),
            "f-9b-no": _result("Yes"),
            "f-reason-0": _result("Placed in removal proceedings; NTA issued."),
            "f-outcome-0": _result(""),
        }
        issues = service._validate_i914_category_consistency(
            targets=targets,
            results_by_id=results_by_id,
            answers={},
            evidence_by_id={},
            classified_events=[],
        )
        review_issues = [i for i in issues if i.get("severity") == "review"]
        self.assertTrue(
            any(i["item_id"] == "p4_9b" for i in review_issues),
            f"Expected a review issue on p4_9b, got: {issues}",
        )

    def test_p4_1g_yes_without_jail_prison_evidence_is_downgraded(self) -> None:
        targets = [
            _yes_no_target("f-1g-yes", "p4_1g", "yes"),
            _yes_no_target("f-1g-no", "p4_1g", "no"),
        ]
        results_by_id = {
            "f-1g-yes": _result("Yes"),
            "f-1g-no": _result(""),
        }
        issues = service._validate_i914_category_consistency(
            targets=targets,
            results_by_id=results_by_id,
            answers={},
            evidence_by_id={},
            classified_events=[],
        )
        downgraded = [i for i in issues if i.get("severity") == "downgrade"]
        self.assertTrue(
            any(i["item_id"] == "p4_1g" for i in downgraded),
            f"Expected p4_1g downgrade issue, got: {issues}",
        )
        self.assertEqual(results_by_id["f-1g-yes"]["value"], "")
        self.assertEqual(results_by_id["f-1g-no"]["value"], "Yes")

    def test_p4_1g_yes_with_jail_prison_evidence_is_preserved(self) -> None:
        targets = [
            _yes_no_target("f-1g-yes", "p4_1g", "yes"),
            _yes_no_target("f-1g-no", "p4_1g", "no"),
        ]
        results_by_id = {
            "f-1g-yes": _result("Yes"),
            "f-1g-no": _result(""),
        }
        event = ClassifiedEvent(
            category=EventCategory.JAIL_PRISON,
            source_tier=1,
            authority_kind="criminal",
        )
        issues = service._validate_i914_category_consistency(
            targets=targets,
            results_by_id=results_by_id,
            answers={},
            evidence_by_id={},
            classified_events=[event],
        )
        downgraded_for_1g = [
            i for i in issues
            if i.get("severity") == "downgrade" and i.get("item_id") == "p4_1g"
        ]
        self.assertFalse(downgraded_for_1g)
        self.assertEqual(results_by_id["f-1g-yes"]["value"], "Yes")

    def test_p3_8_no_without_prior_entries_flags_review(self) -> None:
        targets = [
            {
                "id": "f-p3-8-prior",
                "questionnaire_item_id": "p3_8",
                "questionnaire_field_id": "prior_entry_date_1",
            }
        ]
        results_by_id = {"f-p3-8-prior": _result("")}
        issues = service._validate_i914_category_consistency(
            targets=targets,
            results_by_id=results_by_id,
            answers={"p3_8": "no"},
            evidence_by_id={},
            classified_events=[],
        )
        self.assertTrue(
            any(i["item_id"] == "p3_8" and i["severity"] == "review" for i in issues),
            f"Expected a review issue on p3_8, got: {issues}",
        )

    def test_manually_corrected_yes_keeps_answer_as_info(self) -> None:
        targets = [
            _yes_no_target("f-1g-yes", "p4_1g", "yes"),
            _yes_no_target("f-1g-no", "p4_1g", "no"),
        ]
        results_by_id = {
            "f-1g-yes": _result("Yes"),
            "f-1g-no": _result(""),
        }
        answers = {"p4_1g": {"value": "yes", "manually_corrected": True}}
        issues = service._validate_i914_category_consistency(
            targets=targets,
            results_by_id=results_by_id,
            answers=answers,
            evidence_by_id={},
            classified_events=[],
        )
        info_issues = [i for i in issues if i.get("severity") == "info"]
        self.assertTrue(any(i["item_id"] == "p4_1g" for i in info_issues))
        self.assertEqual(results_by_id["f-1g-yes"]["value"], "Yes")


class DedupePart4DetailRowsTests(unittest.TestCase):
    def test_duplicate_rows_are_cleared(self) -> None:
        targets = []
        results_by_id: dict[str, dict[str, str]] = {}
        for row_index in (0, 1, 2):
            for field_key in (
                "incident_reason",
                "incident_date",
                "incident_location",
                "incident_outcome",
            ):
                field_id = f"f-{row_index}-{field_key}"
                targets.append(_detail_target(field_id, field_key, row_index))
                results_by_id[field_id] = _result("")
        # Row 0 and row 1 have the same values; row 2 is different.
        for field_key, value in (
            ("incident_reason", "Criminal conviction"),
            ("incident_date", "2020-03-15"),
            ("incident_location", "Houston, TX"),
            ("incident_outcome", "10 days in jail"),
        ):
            results_by_id[f"f-0-{field_key}"]["value"] = value
            results_by_id[f"f-1-{field_key}"]["value"] = value
            results_by_id[f"f-2-{field_key}"]["value"] = value + " v2"

        cleared = service._dedupe_part4_detail_rows(targets, results_by_id)
        self.assertEqual(cleared, 4)
        # Row 1 cleared.
        for field_key in (
            "incident_reason",
            "incident_date",
            "incident_location",
            "incident_outcome",
        ):
            self.assertEqual(results_by_id[f"f-1-{field_key}"]["value"], "")
        # Row 0 preserved.
        self.assertEqual(results_by_id["f-0-incident_reason"]["value"], "Criminal conviction")
        # Row 2 preserved.
        self.assertEqual(
            results_by_id["f-2-incident_reason"]["value"], "Criminal conviction v2"
        )


class DedupePart4DetailRowsBySlotIndexTests(unittest.TestCase):
    """Covers the fallback to ``repeatable_slot_index`` when the questionnaire
    target does not carry an explicit ``questionnaire_row_index`` attribute."""

    def test_dedupe_uses_repeatable_slot_index_when_row_index_missing(self) -> None:
        targets: list[dict] = []
        results_by_id: dict[str, dict[str, str]] = {}
        for slot_index in (0, 1):
            for field_key in (
                "incident_reason",
                "incident_date",
                "incident_location",
                "incident_outcome",
            ):
                field_id = f"slot-{slot_index}-{field_key}"
                targets.append(
                    {
                        "id": field_id,
                        "questionnaire_item_id": "p4_1_details",
                        "questionnaire_field_id": field_key,
                        "repeatable_slot_index": slot_index,
                    }
                )
                results_by_id[field_id] = _result("Immigration detention")
                if field_key == "incident_date":
                    results_by_id[field_id] = _result("09/01/1995")
                if field_key == "incident_location":
                    results_by_id[field_id] = _result("Calexico, CA")
                if field_key == "incident_outcome":
                    results_by_id[field_id] = _result("Processed and released")

        cleared = service._dedupe_part4_detail_rows(targets, results_by_id)
        self.assertEqual(cleared, 4)
        for field_key in (
            "incident_reason",
            "incident_date",
            "incident_location",
            "incident_outcome",
        ):
            self.assertEqual(results_by_id[f"slot-1-{field_key}"]["value"], "")
            self.assertNotEqual(results_by_id[f"slot-0-{field_key}"]["value"], "")

    def test_dedupe_when_both_rows_collapse_to_same_slot_index(self) -> None:
        """When slot-index inference maps both physical rows to index 0, the
        field-ID grouping pass must still detect and clear the duplicate."""
        targets: list[dict] = []
        results_by_id: dict[str, dict[str, str]] = {}
        for row_num in (0, 1):
            for field_key in (
                "incident_reason",
                "incident_date",
                "incident_location",
                "incident_outcome",
            ):
                field_id = f"row{row_num}-{field_key}"
                targets.append(
                    {
                        "id": field_id,
                        "questionnaire_item_id": "p4_1_details",
                        "questionnaire_field_id": field_key,
                    }
                )
                value = {
                    "incident_reason": "Immigration detention",
                    "incident_date": "09/01/1995",
                    "incident_location": "Calexico, CA",
                    "incident_outcome": "Processed and released",
                }[field_key]
                results_by_id[field_id] = _result(value)

        cleared = service._dedupe_part4_detail_rows(targets, results_by_id)
        self.assertEqual(cleared, 4)
        for field_key in (
            "incident_reason",
            "incident_date",
            "incident_location",
            "incident_outcome",
        ):
            self.assertNotEqual(
                results_by_id[f"row0-{field_key}"]["value"], "",
                f"First physical row field {field_key} should be preserved",
            )
            self.assertEqual(
                results_by_id[f"row1-{field_key}"]["value"], "",
                f"Second physical row field {field_key} should be cleared",
            )


class Part4TableOutcomeDefaultTests(unittest.TestCase):
    """Ensures the Part 4 table never ships with a blank disposition cell for
    a Yes answer."""

    def test_default_outcome_for_immigration_detention(self) -> None:
        text = service._i914_default_outcome_for_category("immigration_detention")
        self.assertEqual(text, "Processed and released")

    def test_default_outcome_for_unknown_category(self) -> None:
        text = service._i914_default_outcome_for_category("")
        self.assertTrue(text)
        self.assertIn("confirm", text.lower())

    def test_infer_category_from_reason_text(self) -> None:
        self.assertEqual(
            service._i914_infer_category_from_reason_text("Immigration detention"),
            "immigration_detention",
        )
        self.assertEqual(
            service._i914_infer_category_from_reason_text("Convicted of DUI"),
            "conviction",
        )
        self.assertEqual(
            service._i914_infer_category_from_reason_text("Probation sentence"),
            "probation_parole_suspended",
        )
        self.assertEqual(
            service._i914_infer_category_from_reason_text(""),
            "",
        )

    def test_fill_missing_outcome_cell_fills_only_first_slot(self) -> None:
        targets = [
            {
                "id": "outcome-0",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_outcome",
                "repeatable_slot_index": 0,
            },
            {
                "id": "outcome-1",
                "questionnaire_item_id": "p4_1_details",
                "questionnaire_field_id": "incident_outcome",
                "repeatable_slot_index": 1,
            },
        ]
        results_by_id = {"outcome-0": _result(""), "outcome-1": _result("")}
        service._i914_fill_missing_outcome_cell(
            targets=targets,
            results_by_id=results_by_id,
            saved_row={
                "incident_reason": "Immigration detention",
                "incident_outcome": "",
            },
        )
        self.assertTrue(results_by_id["outcome-0"]["value"])
        self.assertEqual(results_by_id["outcome-1"]["value"], "")


class MergePart9EntriesTests(unittest.TestCase):
    """Covers the merge logic that protects manual edits and scrubs stale text."""

    def test_stale_legacy_wording_is_replaced_by_fresh_derived_text(self) -> None:
        existing = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": (
                    "The applicant on 09/01/1995 in Calexico, CA was "
                    "detained/arrested by law enforcement."
                ),
            }
        ]
        derived = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": (
                    "The applicant was detained by immigration authorities "
                    "on 09/01/1995 in or near Calexico, CA. Reason: Immigration detention."
                ),
            }
        ]
        merged = service._merge_i914_part9_entries(existing, derived)
        self.assertEqual(len(merged), 1)
        merged_text = merged[0]["additional_information"]
        self.assertNotIn("detained/arrested by law enforcement", merged_text)
        self.assertIn("immigration authorities", merged_text)

    def test_manual_edit_flag_prevents_overwrite(self) -> None:
        existing = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "My own custom narrative.",
                "manually_edited": True,
            }
        ]
        derived = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "Auto narrative",
            }
        ]
        merged = service._merge_i914_part9_entries(existing, derived)
        self.assertEqual(merged[0]["additional_information"], "My own custom narrative.")

    def test_empty_existing_row_gets_filled_with_derived_text(self) -> None:
        existing = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "",
            }
        ]
        derived = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "Derived narrative.",
            }
        ]
        # An entirely-empty existing row is filtered out by has_content, so the
        # derived row is appended; both behaviours produce the same narrative.
        merged = service._merge_i914_part9_entries(existing, derived)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["additional_information"], "Derived narrative.")

    def test_non_stale_existing_text_is_preserved(self) -> None:
        existing = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "Applicant was detained by CBP on 01/01/2020 in El Paso, TX. Reason: inspection.",
            }
        ]
        derived = [
            {
                "page_number": "4",
                "part_number": "4",
                "item_number": "1.B",
                "additional_information": "Different derived narrative.",
            }
        ]
        merged = service._merge_i914_part9_entries(existing, derived)
        self.assertIn("CBP", merged[0]["additional_information"])


class BuildI914Part9NarrativeTests(unittest.TestCase):
    """Ensures Part 3 Q8/Q9 always emit a compliant narrative (never bare Yes/No)."""

    def _p3_item(self, item_id: str, form_text: str) -> dict:
        return {"id": item_id, "form_text": form_text}

    def test_p3_8_no_without_prior_entries_emits_manual_review_placeholder(self) -> None:
        narrative = service._build_i914_part9_additional_information(
            item=self._p3_item(
                "p3_8", "This is the first time I have entered the United States."
            ),
            normalized_answer="no",
            answers={"p3_8": "no"},
        )
        self.assertIn("Answer: No", narrative)
        self.assertIn("entered the United States previously", narrative)
        self.assertNotEqual(narrative.strip(), "Question: This is the first time I have entered the United States.. Answer: No.")

    def test_p3_8_no_with_prior_entries_lists_them(self) -> None:
        narrative = service._build_i914_part9_additional_information(
            item=self._p3_item(
                "p3_8", "This is the first time I have entered the United States."
            ),
            normalized_answer="no",
            answers={
                "p3_8": "no",
                "p3_8.prior_entry_date": ["01/02/2020"],
                "p3_8.prior_entry_city": ["San Ysidro"],
                "p3_8.prior_entry_state": ["CA"],
                "p3_8.prior_entry_status": ["B-2"],
            },
        )
        self.assertIn("San Ysidro, CA", narrative)
        self.assertIn("Entry 1", narrative)

    def test_p3_9_yes_without_events_still_explains_trafficking_nexus(self) -> None:
        narrative = service._build_i914_part9_additional_information(
            item=self._p3_item(
                "p3_9",
                "My most recent entry was on account of the trafficking in persons.",
            ),
            normalized_answer="yes",
            answers={"p3_9": "yes"},
        )
        self.assertIn("Answer: Yes", narrative)
        self.assertIn("Most recent arrival", narrative)
        self.assertIn("trafficking", narrative.lower())
        self.assertIn("on or about", narrative.lower())

    def test_p4_1b_yes_without_events_uses_placeholder_template(self) -> None:
        narrative = service._build_i914_part9_additional_information(
            item={"id": "p4_1b", "form_text": "Have you ever been detained?"},
            normalized_answer="yes",
            answers={"p4_1b": "yes"},
        )
        self.assertIn("Answer: Yes", narrative)
        lowered = narrative.lower()
        self.assertIn("on or about", lowered)
        self.assertIn("in or near", lowered)
        self.assertIn("immigration authorities", lowered)
        self.assertNotIn("arrested by law enforcement", lowered)

    def test_p4_9d_yes_without_events_uses_placeholder_template(self) -> None:
        narrative = service._build_i914_part9_additional_information(
            item={"id": "p4_9d", "form_text": "Ever ordered to be removed?"},
            normalized_answer="yes",
            answers={"p4_9d": "yes"},
        )
        self.assertIn("ordered", narrative.lower())
        self.assertIn("on or about", narrative.lower())


class DowngradeYesAnswerToNoTests(unittest.TestCase):
    def test_downgrade_sets_yes_cell_empty_and_no_cell_yes(self) -> None:
        targets = [
            _yes_no_target("f-yes", "p4_1g", "yes"),
            _yes_no_target("f-no", "p4_1g", "no"),
        ]
        results_by_id = {
            "f-yes": _result("Yes"),
            "f-no": _result(""),
        }
        changed = service._downgrade_yes_answer_to_no(
            targets=targets,
            results_by_id=results_by_id,
            question_id="p4_1g",
            justification="Test downgrade",
        )
        self.assertTrue(changed)
        self.assertEqual(results_by_id["f-yes"]["value"], "")
        self.assertEqual(results_by_id["f-no"]["value"], "Yes")


if __name__ == "__main__":
    unittest.main()
