"""Unit tests for the I-914 event taxonomy module.

Covers the eight scenarios described in the refactor plan:

1. CBP detention without NTA activates only IMMIGRATION_DETENTION (p4_1b).
2. CBP detention + NTA activates both IMMIGRATION_DETENTION and NTA_ISSUED.
3. "Ordered removed" in an FBI / court record tier 1 activates REMOVAL_ORDER.
4. "CBP hold 4 hours, released same day" does NOT activate JAIL_PRISON.
5. Conviction + jail sentence tier 1 activates CONVICTION and JAIL_PRISON.
6. Diversion program activates DIVERSION_DEFERRED_WITHHELD, not CONVICTION.
7. Tier-3 narrative mentioning "removal order" does NOT escalate (min_tier
   violated).
8. build_part4_table_rows / build_part9_text emit the conservative fallbacks
   ("on or about", "in or near", "if known") when slots are missing.
"""

import unittest

from app.services.i914_event_taxonomy import (
    ClassifiedEvent,
    EventCategory,
    build_part4_table_rows,
    build_part9_text,
    classify_evidence_events,
    detect_category_conflicts,
    map_events_to_part4_items,
    placeholder_event_for_item,
)


def _evidence(text: str, tier: int = 1) -> dict:
    return {"text": text, "tier": tier, "page": 1, "source": "test"}


class ClassifyEvidenceEventsTests(unittest.TestCase):
    def test_cbp_detention_without_nta_activates_only_detention(self) -> None:
        evidence = [
            _evidence(
                "On 03/15/2022, the applicant was detained by CBP at Laredo, TX. "
                "She was processed and later released.",
                tier=2,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertIn(EventCategory.IMMIGRATION_DETENTION, categories)
        self.assertNotIn(EventCategory.NTA_ISSUED, categories)
        self.assertNotIn(EventCategory.REMOVAL_ORDER, categories)

        mapping = map_events_to_part4_items(events)
        self.assertIn("p4_1b", mapping)
        self.assertNotIn("p4_9b", mapping)
        self.assertNotIn("p4_9d", mapping)

    def test_cbp_detention_with_nta_activates_both(self) -> None:
        evidence = [
            _evidence(
                "On 03/15/2022 the applicant was detained by CBP in Laredo, TX. "
                "A Notice to Appear was issued and she was placed in removal proceedings.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertIn(EventCategory.IMMIGRATION_DETENTION, categories)
        self.assertIn(EventCategory.NTA_ISSUED, categories)

        mapping = map_events_to_part4_items(events)
        self.assertIn("p4_1b", mapping)
        self.assertIn("p4_9b", mapping)

    def test_ordered_removed_in_court_record_activates_removal_order(self) -> None:
        evidence = [
            _evidence(
                "The applicant was ordered removed from the United States on 06/02/2019 "
                "by the immigration judge in San Antonio, TX.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertIn(EventCategory.REMOVAL_ORDER, categories)
        mapping = map_events_to_part4_items(events)
        self.assertIn("p4_9d", mapping)

    def test_brief_cbp_hold_does_not_activate_jail_prison(self) -> None:
        evidence = [
            _evidence(
                "CBP hold: the applicant was held by CBP for 4 hours and released the same day.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertNotIn(EventCategory.JAIL_PRISON, categories)
        self.assertIn(EventCategory.IMMIGRATION_DETENTION, categories)

    def test_conviction_with_jail_sentence_activates_both(self) -> None:
        evidence = [
            _evidence(
                "On 11/12/2020 the applicant was convicted of a misdemeanor in county court. "
                "The applicant was sentenced to 10 days in jail.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertIn(EventCategory.CONVICTION, categories)
        self.assertIn(EventCategory.JAIL_PRISON, categories)

        mapping = map_events_to_part4_items(events)
        self.assertIn("p4_1d", mapping)
        self.assertIn("p4_1g", mapping)

    def test_diversion_program_activates_diversion_not_conviction(self) -> None:
        evidence = [
            _evidence(
                "The applicant participated in a pretrial diversion program for a minor offense. "
                "No conviction was entered by the court.",
                tier=2,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertIn(EventCategory.DIVERSION_DEFERRED_WITHHELD, categories)
        self.assertNotIn(EventCategory.CONVICTION, categories)

        mapping = map_events_to_part4_items(events)
        self.assertIn("p4_1e", mapping)
        self.assertNotIn("p4_1d", mapping)

    def test_tier3_narrative_does_not_escalate_to_removal_order(self) -> None:
        evidence = [
            _evidence(
                "During BioCall intake, the applicant mentioned she had been ordered removed "
                "at some point in the past.",
                tier=3,
            )
        ]
        events = classify_evidence_events(evidence)
        categories = {e.category for e in events}

        self.assertNotIn(EventCategory.REMOVAL_ORDER, categories)
        # Tier 3 source can't feed a hard category requiring tier <= 2.


class BuildTemplatesTests(unittest.TestCase):
    def test_part4_table_rows_use_default_reason_when_reason_is_generic(self) -> None:
        # Build a synthetic event with a generic reason to force the default
        # category reason fallback inside build_part4_table_rows.
        synthetic = ClassifiedEvent(
            category=EventCategory.IMMIGRATION_DETENTION,
            date="",
            authority="CBP",
            authority_kind="immigration",
            location_city="",
            location_state="",
            outcome="",
            reason="Detained.",
            raw_text="Detained.",
            source_tier=2,
        )
        rows = build_part4_table_rows([synthetic])

        self.assertTrue(rows)
        self.assertEqual(rows[0]["incident_reason"], "Immigration detention")

    def test_part4_table_rows_normalize_immigration_detention_reason(self) -> None:
        synthetic = ClassifiedEvent(
            category=EventCategory.IMMIGRATION_DETENTION,
            date="09/01/1995",
            authority="CBP",
            authority_kind="immigration",
            location_city="Calexico",
            location_state="CA",
            outcome="",
            reason="CBP records show the applicant was detained on 09/01/1995 in Calexico, CA.",
            raw_text="CBP records show the applicant was detained on 09/01/1995 in Calexico, CA.",
            source_tier=1,
        )

        rows = build_part4_table_rows([synthetic])

        self.assertTrue(rows)
        self.assertEqual(rows[0]["incident_reason"], "Immigration detention")

    def test_part9_text_falls_back_to_conservative_wording(self) -> None:
        evidence = [
            _evidence(
                "The applicant was detained by CBP.",
                tier=2,
            )
        ]
        events = classify_evidence_events(evidence)
        text = build_part9_text("p4_1b", events)

        lowered = text.lower()
        self.assertIn("on or about", lowered)
        self.assertIn("in or near", lowered)
        self.assertTrue("cbp" in lowered or "immigration authorities" in lowered)

    def test_part9_text_branches_per_item_id(self) -> None:
        evidence = [
            _evidence(
                "On 04/01/2021 the applicant was convicted of a misdemeanor in Harris County, TX.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        text_1d = build_part9_text("p4_1d", events)
        text_1c = build_part9_text("p4_1c", [])

        self.assertIn("convicted", text_1d.lower())
        self.assertEqual(text_1c, "")


class PlaceholderEventTests(unittest.TestCase):
    """Covers the placeholder events emitted for Yes answers without facts."""

    def test_placeholder_for_p4_1b_renders_immigration_fallbacks(self) -> None:
        placeholder = placeholder_event_for_item("p4_1b")
        self.assertIsNotNone(placeholder)
        self.assertEqual(placeholder.category, EventCategory.IMMIGRATION_DETENTION)
        self.assertEqual(placeholder.authority_kind, "immigration")
        text = build_part9_text("p4_1b", [placeholder]).lower()
        self.assertIn("on or about", text)
        self.assertIn("in or near", text)
        self.assertIn("immigration authorities", text)
        self.assertNotIn("arrested by law enforcement", text)

    def test_placeholder_for_p3_9_uses_trafficking_nexus_wording(self) -> None:
        placeholder = placeholder_event_for_item("p3_9")
        self.assertIsNotNone(placeholder)
        text = build_part9_text("p3_9", [placeholder]).lower()
        self.assertIn("most recent arrival", text)
        self.assertIn("trafficking", text)
        self.assertIn("on or about", text)

    def test_placeholder_for_p4_1d_uses_conviction_template(self) -> None:
        placeholder = placeholder_event_for_item("p4_1d")
        self.assertIsNotNone(placeholder)
        text = build_part9_text("p4_1d", [placeholder]).lower()
        self.assertIn("convicted", text)
        self.assertIn("on or about", text)

    def test_placeholder_for_p4_9d_mentions_removal_order(self) -> None:
        placeholder = placeholder_event_for_item("p4_9d")
        self.assertIsNotNone(placeholder)
        text = build_part9_text("p4_9d", [placeholder]).lower()
        self.assertIn("ordered", text)
        self.assertIn("immigration authorities", text)

    def test_placeholder_for_unknown_item_returns_none(self) -> None:
        self.assertIsNone(placeholder_event_for_item("unknown_item"))


class DetectConflictsTests(unittest.TestCase):
    def test_missing_yes_conflict_when_strong_evidence_contradicts_no(self) -> None:
        evidence = [
            _evidence(
                "The applicant was detained by CBP at Laredo, TX on 03/15/2022. "
                "A Notice to Appear was issued.",
                tier=1,
            )
        ]
        events = classify_evidence_events(evidence)
        conflicts = detect_category_conflicts(events, {"p4_9b": "no", "p4_1b": "no"})
        items_with_conflicts = {c["item_id"] for c in conflicts if c["kind"] == "missing_yes"}
        self.assertIn("p4_9b", items_with_conflicts)
        self.assertIn("p4_1b", items_with_conflicts)

    def test_unsupported_yes_conflict_when_no_evidence_backs_answer(self) -> None:
        conflicts = detect_category_conflicts([], {"p4_1g": "yes"})
        items = {(c["item_id"], c["kind"]) for c in conflicts}
        self.assertIn(("p4_1g", "unsupported_yes"), items)


if __name__ == "__main__":
    unittest.main()
