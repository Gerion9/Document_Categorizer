"""Smoke tests for the central form registry.

The registry is the single source of truth for every USCIS form we support.
These tests are deliberately fast and dependency-free so they can run in any
environment that imports `app.services.form_registry`.
"""

import unittest

from app.services import form_registry


class FormRegistryTests(unittest.TestCase):
    def test_registry_is_non_empty_and_keys_match_form_type(self) -> None:
        self.assertGreater(len(form_registry.FORM_REGISTRY), 0)
        for key, spec in form_registry.FORM_REGISTRY.items():
            self.assertEqual(
                key,
                spec.form_type,
                f"Registry key '{key}' does not match FormSpec.form_type '{spec.form_type}'.",
            )

    def test_form_types_are_canonical(self) -> None:
        for key in form_registry.FORM_REGISTRY:
            self.assertEqual(
                key,
                form_registry.normalize_form_type(key),
                f"Registry key '{key}' is not in canonical normalized form.",
            )

    def test_i914a_is_not_registered_until_seed_pdf_exists(self) -> None:
        self.assertNotIn("i-914a", form_registry.FORM_REGISTRY)
        self.assertIsNone(form_registry.get_form_spec_or_none("i-914a"))

    def test_each_spec_has_required_metadata(self) -> None:
        for spec in form_registry.FORM_REGISTRY.values():
            self.assertTrue(spec.label)
            self.assertTrue(spec.description)
            self.assertIn(spec.category, ("visa-t", "cgis"))
            self.assertTrue(spec.pdf_filename)
            self.assertTrue(spec.client_json)
            self.assertTrue(spec.qc_template_module)
            self.assertTrue(spec.qc_template_symbol)
            self.assertTrue(spec.prompt_module)

    def test_pdf_files_exist_on_disk(self) -> None:
        missing = [
            spec.pdf_filename
            for spec in form_registry.FORM_REGISTRY.values()
            if not spec.pdf_path().exists()
        ]
        self.assertEqual(missing, [])

    def test_questionnaire_json_files_exist_on_disk(self) -> None:
        for spec in form_registry.FORM_REGISTRY.values():
            self.assertTrue(
                spec.client_json_path().exists(),
                f"Missing client JSON for {spec.form_type}: {spec.client_json_path()}",
            )
            attorney_path = spec.attorney_json_path()
            if attorney_path is not None:
                self.assertTrue(
                    attorney_path.exists(),
                    f"Missing attorney JSON for {spec.form_type}: {attorney_path}",
                )

    def test_normalize_form_type_handles_common_variations(self) -> None:
        cases = {
            "I-914": "i-914",
            "i914": "i-914",
            "Form I-914": "i-914",
            "form i914": "i-914",
            "I-914A": "i-914a",
            "I914a": "i-914a",
            "g28": "g-28",
            "G-28": "g-28",
            "G 1145": "g-1145",
        }
        for raw, expected in cases.items():
            self.assertEqual(
                form_registry.normalize_form_type(raw),
                expected,
                f"normalize_form_type({raw!r}) -> expected {expected!r}",
            )

    def test_normalize_form_type_returns_none_for_empty(self) -> None:
        self.assertIsNone(form_registry.normalize_form_type(""))
        self.assertIsNone(form_registry.normalize_form_type(None))

    def test_compact_form_type_strips_dash(self) -> None:
        self.assertEqual(form_registry.compact_form_type("i-914"), "i914")
        self.assertEqual(form_registry.compact_form_type("I-914A"), "i914a")
        self.assertEqual(form_registry.compact_form_type("g-1145"), "g1145")

    def test_get_form_spec_raises_for_unknown(self) -> None:
        with self.assertRaises(KeyError):
            form_registry.get_form_spec("i-9999")

    def test_get_form_spec_or_none_returns_none_for_unknown(self) -> None:
        self.assertIsNone(form_registry.get_form_spec_or_none("i-9999"))

    def test_doc_ai_hints_are_lowercase_phrases(self) -> None:
        for spec in form_registry.FORM_REGISTRY.values():
            for item_id, phrases in spec.doc_ai_hints.items():
                self.assertTrue(item_id, f"Empty item_id in hints for {spec.form_type}")
                for phrase in phrases:
                    self.assertIsInstance(phrase, str)
                    self.assertEqual(
                        phrase,
                        phrase.strip(),
                        f"Hint phrase has leading/trailing whitespace for {spec.form_type}: {phrase!r}",
                    )


if __name__ == "__main__":
    unittest.main()
