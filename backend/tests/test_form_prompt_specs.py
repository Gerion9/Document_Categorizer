"""Each registered form must declare a FormPromptSpec; specs must agree with FormSpec."""

import unittest

from app.prompts.forms import FORM_PROMPT_REGISTRY, try_get_form_prompt_spec
from app.services import form_registry


class FormPromptSpecsTests(unittest.TestCase):
    def test_every_registered_form_has_a_prompt_spec(self) -> None:
        missing = [
            spec.form_type
            for spec in form_registry.FORM_REGISTRY.values()
            if spec.form_type not in FORM_PROMPT_REGISTRY
        ]
        self.assertEqual(missing, [], f"Forms without a FormPromptSpec: {missing}")

    def test_prompt_specs_match_form_registry(self) -> None:
        for form_type, prompt_spec in FORM_PROMPT_REGISTRY.items():
            form_spec = form_registry.get_form_spec_or_none(form_type)
            self.assertIsNotNone(
                form_spec,
                f"FormPromptSpec exists for unknown form_type {form_type!r}",
            )
            assert form_spec is not None  # type narrowing for mypy/readers
            self.assertEqual(
                prompt_spec.form_type,
                form_spec.form_type,
                f"Mismatched form_type between prompt spec and FormSpec for {form_type}",
            )

    def test_try_get_form_prompt_spec_returns_none_for_unknown(self) -> None:
        self.assertIsNone(try_get_form_prompt_spec("i-9999"))
        self.assertIsNone(try_get_form_prompt_spec(""))
        self.assertIsNone(try_get_form_prompt_spec(None))

    def test_try_get_form_prompt_spec_returns_spec_for_normalized_input(self) -> None:
        spec = try_get_form_prompt_spec("I-914")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.form_type, "i-914")


if __name__ == "__main__":
    unittest.main()
