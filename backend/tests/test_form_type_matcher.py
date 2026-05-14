import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import form_type_matcher as matcher
from app.services.pdf_form_service import detect_form_fields


def _build_definition(
    *,
    item_id: str,
    field_id: str,
    page_number: int,
    section: str,
    form_text: str,
    label: str,
    item_type: str = "text",
    field_type_hint: str = "text",
) -> matcher.QuestionnaireFieldDefinition:
    canonical_id = f"{item_id}.{field_id}"
    search_text = " ".join(part for part in [section, form_text, label, item_id, field_id] if part)
    return matcher.QuestionnaireFieldDefinition(
        definition_id=canonical_id,
        canonical_questionnaire_id=canonical_id,
        form_type="i-914",
        page_number=page_number,
        responsible_party="client",
        item_id=item_id,
        item_code=item_id.upper(),
        item_type=item_type,
        section=section,
        form_text=form_text,
        label=label,
        field_id=field_id,
        option_value=None,
        option_label=None,
        source_file="test.json",
        field_type_hint=field_type_hint,
        qc_description="",
        qc_where_to_verify="",
        search_text=search_text,
        tokens=frozenset(matcher._tokenize(search_text)),
    )


class FormTypeMatcherTests(unittest.TestCase):
    def _run_mapping(
        self,
        pdf_field: dict[str, object],
        definitions: list[matcher.QuestionnaireFieldDefinition],
        score_by_id: dict[str, float],
    ) -> dict[str, object]:
        def fake_score(
            _: dict[str, object],
            definition: matcher.QuestionnaireFieldDefinition,
            **__: object,
        ) -> float:
            return score_by_id[definition.canonical_questionnaire_id]

        with (
            patch.object(matcher, "load_questionnaire_definition", return_value={"source_files": ["test.json"]}),
            patch.object(matcher, "_questionnaire_field_definitions", return_value=tuple(definitions)),
            patch.object(matcher, "_score_field_match", side_effect=fake_score),
        ):
            return matcher.map_pdf_fields_to_questionnaire_ids("i-914", [pdf_field])

    def test_rejects_candidate_below_second_pass_floor(self) -> None:
        definition = _build_definition(
            item_id="part1_name",
            field_id="given_name",
            page_number=1,
            section="Part 1. Information About You",
            form_text="Given Name (First Name)",
            label="Given Name (First Name)",
        )
        result = self._run_mapping(
            {
                "field_name": "given_name_1",
                "field_label": "",
                "nearby_text": "",
                "field_type": "text",
                "field_type_hint": "text",
                "button_values": [],
                "choice_values": [],
                "page_number": 1,
            },
            [definition],
            {definition.canonical_questionnaire_id: 0.17},
        )

        mapping = result["mappings"][0]
        self.assertIsNone(mapping["canonical_questionnaire_id"])
        self.assertEqual(result["matched_count"], 0)
        self.assertEqual(result["unmatched_count"], 1)
        self.assertAlmostEqual(mapping["match_score"], 0.17)

    def test_second_pass_rescues_borderline_match_with_specific_context(self) -> None:
        definition = _build_definition(
            item_id="part1_name",
            field_id="given_name",
            page_number=1,
            section="Part 1. Information About You",
            form_text="Given Name (First Name)",
            label="Given Name (First Name)",
        )
        result = self._run_mapping(
            {
                "field_name": "given_name_1",
                "field_label": "Given Name (First Name)",
                "nearby_text": "Part 1. Information About You | Given Name (First Name)",
                "field_type": "text",
                "field_type_hint": "text",
                "button_values": [],
                "choice_values": [],
                "page_number": 1,
            },
            [definition],
            {definition.canonical_questionnaire_id: 0.24},
        )

        mapping = result["mappings"][0]
        self.assertEqual(mapping["canonical_questionnaire_id"], definition.canonical_questionnaire_id)
        self.assertEqual(mapping["matched_label"], definition.label)
        self.assertEqual(mapping["confidence"], "high")

    def test_second_pass_prefers_more_specific_context(self) -> None:
        legal_name = _build_definition(
            item_id="part1_name",
            field_id="family_name",
            page_number=1,
            section="Part 1. Information About You",
            form_text="Full Legal Name",
            label="Family Name (Last Name)",
        )
        other_names = _build_definition(
            item_id="part2_other_names",
            field_id="family_name",
            page_number=2,
            section="Part 2. Other Names Used",
            form_text="Other Names Used Since Birth",
            label="Family Name (Last Name)",
        )

        result = self._run_mapping(
            {
                "field_name": "family_name_2",
                "field_label": "Family Name (Last Name)",
                "nearby_text": "Other Names Used Since Birth | Family Name (Last Name)",
                "field_type": "text",
                "field_type_hint": "text",
                "button_values": [],
                "choice_values": [],
                "page_number": 2,
            },
            [legal_name, other_names],
            {
                legal_name.canonical_questionnaire_id: 0.47,
                other_names.canonical_questionnaire_id: 0.45,
            },
        )

        mapping = result["mappings"][0]
        self.assertEqual(mapping["canonical_questionnaire_id"], other_names.canonical_questionnaire_id)
        self.assertEqual(mapping["matched_section"], other_names.section)
        self.assertEqual(mapping["confidence"], "high")

    def test_second_pass_leaves_field_unmatched_when_tie_persists(self) -> None:
        first_candidate = _build_definition(
            item_id="part1_name",
            field_id="family_name",
            page_number=1,
            section="Part 1. Information About You",
            form_text="Family Name (Last Name)",
            label="Family Name (Last Name)",
        )
        second_candidate = _build_definition(
            item_id="part4_household",
            field_id="family_name",
            page_number=3,
            section="Part 4. Household Members",
            form_text="Family Name (Last Name)",
            label="Family Name (Last Name)",
        )

        result = self._run_mapping(
            {
                "field_name": "family_name_generic",
                "field_label": "Family Name (Last Name)",
                "nearby_text": "",
                "field_type": "text",
                "field_type_hint": "text",
                "button_values": [],
                "choice_values": [],
                "page_number": None,
            },
            [first_candidate, second_candidate],
            {
                first_candidate.canonical_questionnaire_id: 0.47,
                second_candidate.canonical_questionnaire_id: 0.45,
            },
        )

        mapping = result["mappings"][0]
        self.assertIsNone(mapping["canonical_questionnaire_id"])
        self.assertEqual(result["matched_count"], 0)
        self.assertAlmostEqual(mapping["match_score"], 0.93)

    def test_second_pass_prefers_state_field_in_address_triplet(self) -> None:
        city = _build_definition(
            item_id="p2_3",
            field_id="city",
            page_number=1,
            section="Part 2. General Information About You",
            form_text="Physical Address",
            label="City or Town",
        )
        state = _build_definition(
            item_id="p2_3",
            field_id="state",
            page_number=1,
            section="Part 2. General Information About You",
            form_text="Physical Address",
            label="State",
            item_type="select",
            field_type_hint="choice",
        )
        zip_code = _build_definition(
            item_id="p2_3",
            field_id="zip_code",
            page_number=1,
            section="Part 2. General Information About You",
            form_text="Physical Address",
            label="ZIP Code",
        )

        result = self._run_mapping(
            {
                "field_name": "physical_state",
                "field_label": (
                    "Part 2. General Information About You (Person filing this application as a victim). "
                    "3. Physical Address. Select State from the list of States."
                ),
                "nearby_text": "City or Town | State | ZIP Code | Action Block",
                "field_type": "choice",
                "field_type_hint": "choice",
                "button_values": [],
                "choice_values": ["('NY', 'NY')"],
                "page_number": 1,
            },
            [city, state, zip_code],
            {
                city.canonical_questionnaire_id: 1.0,
                state.canonical_questionnaire_id: 1.0,
                zip_code.canonical_questionnaire_id: 1.0,
            },
        )

        mapping = result["mappings"][0]
        self.assertEqual(mapping["canonical_questionnaire_id"], state.canonical_questionnaire_id)
        self.assertEqual(mapping["questionnaire_field_id"], "state")

    def test_second_pass_uses_form_text_to_separate_physical_and_safe_unit_type(self) -> None:
        physical_unit = _build_definition(
            item_id="p2_3",
            field_id="unit_type",
            page_number=1,
            section="Part 2. General Information About You",
            form_text="Physical Address",
            label="Apt./Ste./Flr.",
            item_type="select",
            field_type_hint="choice",
        )
        safe_unit = _build_definition(
            item_id="p2_4",
            field_id="safe_unit_type",
            page_number=1,
            section="Part 2. General Information About You",
            form_text="Safe Mailing Address",
            label="Apt./Ste./Flr.",
            item_type="select",
            field_type_hint="choice",
        )

        result = self._run_mapping(
            {
                "field_name": "physical_unit_apt",
                "field_label": (
                    "Part 2. General Information About You (Person filing this application as a victim). "
                    "3. Physical Address. Check this box for Apartment."
                ),
                "nearby_text": "Stamp # | Apt. | Ste. | Flr.",
                "field_type": "checkbox",
                "field_type_hint": "button",
                "button_values": ["#20APT#20"],
                "choice_values": [],
                "page_number": 1,
            },
            [physical_unit, safe_unit],
            {
                physical_unit.canonical_questionnaire_id: 1.0,
                safe_unit.canonical_questionnaire_id: 0.9591,
            },
        )

        mapping = result["mappings"][0]
        self.assertEqual(mapping["canonical_questionnaire_id"], physical_unit.canonical_questionnaire_id)
        self.assertEqual(mapping["questionnaire_field_id"], "unit_type")

    def test_select_field_expands_options_as_separate_definitions(self) -> None:
        definitions = matcher.list_questionnaire_field_definitions("i-914")
        unit_type_defs = [
            d for d in definitions
            if d["canonical_questionnaire_id"] == "p2_3.unit_type"
        ]
        option_values = [d["option_value"] for d in unit_type_defs if d["option_value"]]
        self.assertIn("Apt.", option_values)
        self.assertIn("Ste.", option_values)
        self.assertIn("Flr.", option_values)
        base_defs = [d for d in unit_type_defs if d["option_value"] is None]
        self.assertTrue(len(base_defs) >= 1, "base definition without option_value must exist")

    def test_i914_definition_includes_prior_entry_detail_fields(self) -> None:
        definitions = matcher.list_questionnaire_field_definitions("i-914")
        by_id = {definition["canonical_questionnaire_id"]: definition for definition in definitions}

        self.assertIn("p3_8.prior_entry_date", by_id)
        self.assertIn("p3_8.prior_entry_city", by_id)
        self.assertIn("p3_8.prior_entry_state", by_id)
        self.assertIn("p3_8.prior_entry_status", by_id)

    def test_i914_template_maps_entry_and_incident_fields(self) -> None:
        pdf_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "seed_data"
            / "forms"
            / "i-914.pdf"
        )
        wanted_field_names = {
            "form1[0].#subform[4].DateofEntry[0]": ("p3_8.prior_entry_date", None),
            "form1[0].#subform[4].PlaceofEntry[0]": ("p3_8.prior_entry_city", None),
            "form1[0].#subform[4].ddState[0]": ("p3_8.prior_entry_state", None),
            "form1[0].#subform[4].Status[0]": ("p3_8.prior_entry_status", None),
            "form1[0].#subform[4].Q7_no[0]": ("p3_7", "no"),
            "form1[0].#subform[4].Q7_yes[0]": ("p3_7", "yes"),
            "form1[0].#subform[4].Q8_no[0]": ("p3_8", "no"),
            "form1[0].#subform[4].Q8_yes[0]": ("p3_8", "yes"),
            "form1[0].#subform[5].Table6[0].Row1[0].Dateofarrestcitationdetentioncharge[0]": (
                "p4_1_details.incident_date",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row1[0].Whywereyouarrestedciteddetainedorcharged[0]": (
                "p4_1_details.incident_reason",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row1[0].Wherewereyouarrestedciteddetainedorcharged[0]": (
                "p4_1_details.incident_location",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row1[0].Outcomeordisposition[0]": (
                "p4_1_details.incident_outcome",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row2[0].Dateofarrestcitationdetentioncharge[0]": (
                "p4_1_details.incident_date",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row2[0].Whywereyouarrestedciteddetainedorcharged[0]": (
                "p4_1_details.incident_reason",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row2[0].Wherewereyouarrestedciteddetainedorcharged[0]": (
                "p4_1_details.incident_location",
                None,
            ),
            "form1[0].#subform[5].Table6[0].Row2[0].Outcomeordisposition[0]": (
                "p4_1_details.incident_outcome",
                None,
            ),
        }

        detected_fields = detect_form_fields(pdf_path)["fields"]
        targeted_fields = [
            field
            for field in detected_fields
            if field.get("field_name") in wanted_field_names
        ]

        result = matcher.map_pdf_fields_to_questionnaire_ids("i-914", targeted_fields)
        by_field_name = {mapping["field_name"]: mapping for mapping in result["mappings"]}

        self.assertEqual(set(by_field_name), set(wanted_field_names))
        for field_name, (expected_canonical_id, expected_option_value) in wanted_field_names.items():
            mapping = by_field_name[field_name]
            self.assertEqual(mapping["canonical_questionnaire_id"], expected_canonical_id, field_name)
            self.assertEqual(mapping["questionnaire_option_value"], expected_option_value, field_name)

    def test_i914_definition_includes_qc_hint(self) -> None:
        definitions = matcher.list_questionnaire_field_definitions("i-914")
        by_id = {definition["canonical_questionnaire_id"]: definition for definition in definitions}

        date_of_birth = by_id["p2_10"]
        self.assertIn("date of birth", date_of_birth["qc_description"].lower())
        self.assertIn("birth cert", date_of_birth["qc_where_to_verify"].lower())

    def test_i192_definition_includes_qc_hint(self) -> None:
        definitions = matcher.list_questionnaire_field_definitions("i-192")
        by_id = {definition["canonical_questionnaire_id"]: definition for definition in definitions}

        a_number = by_id["p2_3"]
        self.assertIn("alien registration number", a_number["qc_description"].lower())
        self.assertIn("previous immigration documents", a_number["qc_where_to_verify"].lower())


if __name__ == "__main__":
    unittest.main()
