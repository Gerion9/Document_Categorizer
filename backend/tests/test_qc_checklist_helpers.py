import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Case, DocumentType, Page
from app.services import qc_checklist_helpers as helpers


class QCChecklistHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.Session()

        case = Case(name="Case")
        self.db.add(case)
        self.db.flush()
        self.case_id = case.id

        birth_cert_type = DocumentType(case_id=self.case_id, name="Birth Certificate", code="BC")
        declaration_type = DocumentType(case_id=self.case_id, name="Declaration", code="DECL")
        self.db.add_all([birth_cert_type, declaration_type])
        self.db.flush()

        self.db.add_all(
            [
                Page(
                    case_id=self.case_id,
                    source_document_id="doc-bio",
                    original_filename="BIO CALL - NATALIA.pdf",
                    document_type_id=None,
                ),
                Page(
                    case_id=self.case_id,
                    source_document_id="doc-bc",
                    original_filename="CAN-7958 NATALIA - BC.pdf",
                    document_type_id=birth_cert_type.id,
                ),
                Page(
                    case_id=self.case_id,
                    source_document_id="doc-decl",
                    original_filename="DECLARATION OF NATALIA IN SUPPORT.pdf",
                    document_type_id=declaration_type.id,
                ),
                Page(
                    case_id=self.case_id,
                    source_document_id="doc-fbi",
                    original_filename="FBI RECORD.pdf",
                    document_type_id=None,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_resolve_source_document_targets_matches_where_to_verify_aliases(self) -> None:
        alias_index = helpers.build_case_source_document_alias_index(self.case_id, self.db)

        resolved = helpers.resolve_source_document_targets(
            "Birth Certificate, FBI; Bio Call",
            alias_index,
        )

        self.assertEqual(resolved, ["doc-bc", "doc-fbi", "doc-bio"])

    def test_resolve_source_document_targets_respects_scope(self) -> None:
        alias_index = helpers.build_case_source_document_alias_index(
            self.case_id,
            self.db,
            source_document_ids=["doc-decl"],
        )

        resolved = helpers.resolve_source_document_targets(
            "Declaration; FBI",
            alias_index,
        )

        self.assertEqual(resolved, ["doc-decl"])


if __name__ == "__main__":
    unittest.main()
