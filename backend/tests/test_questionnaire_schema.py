"""Validate every shipped questionnaire JSON against the Pydantic schema.

`backend/app/schemas/questionnaire_json.py` defines the canonical structure
for questionnaire JSONs. If anyone adds or edits a JSON in
`backend/app/seed_data/questions/` it MUST keep validating cleanly.
"""

import json
import unittest

from pydantic import ValidationError

from app.schemas.questionnaire_json import QuestionnaireDocument
from app.services import form_registry


class QuestionnaireSchemaTests(unittest.TestCase):
    def test_all_registered_questionnaires_validate(self) -> None:
        errors: list[str] = []
        for spec in form_registry.FORM_REGISTRY.values():
            for path in (spec.client_json_path(), spec.attorney_json_path()):
                if path is None or not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(data, list):
                        data = {"pages": data}
                    QuestionnaireDocument.model_validate(data)
                except (ValidationError, json.JSONDecodeError) as exc:
                    errors.append(f"{path.name}: {exc}")
        self.assertEqual(errors, [], "Questionnaire schema violations:\n" + "\n".join(errors))

    def test_every_item_has_an_id(self) -> None:
        for spec in form_registry.FORM_REGISTRY.values():
            for path in (spec.client_json_path(), spec.attorney_json_path()):
                if path is None or not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                pages = data if isinstance(data, list) else data.get("pages", [])
                for page in pages:
                    for item in page.get("items", []) or []:
                        self.assertTrue(
                            item.get("id"),
                            f"Item without id in {path.name} page {page.get('page')}: {item}",
                        )

    def test_item_ids_are_unique_within_each_file(self) -> None:
        for spec in form_registry.FORM_REGISTRY.values():
            for path in (spec.client_json_path(), spec.attorney_json_path()):
                if path is None or not path.exists():
                    continue
                data = json.loads(path.read_text(encoding="utf-8"))
                pages = data if isinstance(data, list) else data.get("pages", [])
                seen: set[str] = set()
                for page in pages:
                    for item in page.get("items", []) or []:
                        item_id = item.get("id")
                        if not item_id:
                            continue
                        self.assertNotIn(
                            item_id,
                            seen,
                            f"Duplicate item id '{item_id}' in {path.name}",
                        )
                        seen.add(item_id)


if __name__ == "__main__":
    unittest.main()
