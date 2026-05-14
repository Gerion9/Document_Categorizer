import unittest

from app.models import Case
from app.services import case_document_scope_service as scope_service


class CaseDocumentScopeServiceTests(unittest.TestCase):
    def test_get_case_scope_source_document_ids_preserves_null_scope(self) -> None:
        case = Case(name="Case scope")
        case.form_filling_source_document_ids = None

        self.assertIsNone(
            scope_service.get_case_scope_source_document_ids(case, "form_filling")
        )

    def test_get_case_scope_source_document_ids_normalizes_duplicates(self) -> None:
        case = Case(name="Case scope")
        case.qc_checklist_source_document_ids = [" doc-1 ", "", "doc-1", "doc-2"]

        self.assertEqual(
            scope_service.get_case_scope_source_document_ids(case, "qc_checklist"),
            ["doc-1", "doc-2"],
        )

    def test_set_case_scope_source_document_ids_handles_lists_and_null(self) -> None:
        case = Case(name="Case scope")

        scope_service.set_case_scope_source_document_ids(
            case,
            "form_filling",
            [" doc-1 ", "doc-1", "doc-2"],
        )
        self.assertEqual(case.form_filling_source_document_ids, ["doc-1", "doc-2"])

        scope_service.set_case_scope_source_document_ids(case, "form_filling", None)
        self.assertIsNone(case.form_filling_source_document_ids)


if __name__ == "__main__":
    unittest.main()
