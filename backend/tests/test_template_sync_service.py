import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import FormTemplate, QCChecklist
from app.services import template_sync_service


class _FakeStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, int, str]] = []

    def upload_bytes(self, content: bytes, key: str, content_type: str) -> str:
        self.uploads.append((key, len(content), content_type))
        return key


class TemplateSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.Session()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_sync_form_templates_updates_existing_rows(self) -> None:
        self.db.add(
            FormTemplate(
                name="Old I-914",
                form_type="i-914",
                description="Old description",
                s3_key="formas/old.pdf",
                original_filename="old.pdf",
                file_size=1,
            )
        )
        self.db.commit()

        fake_storage = _FakeStorage()
        with tempfile.TemporaryDirectory() as tmp_dir:
            forms_dir = Path(tmp_dir)
            (forms_dir / "i-914.pdf").write_bytes(b"new-pdf")

            with patch.object(template_sync_service, "_seed_forms_dir", return_value=forms_dir):
                summary = template_sync_service.sync_form_templates(
                    self.db,
                    storage=fake_storage,
                    seed_items=[
                        {
                            "name": "I-914",
                            "form_type": "i-914",
                            "filename": "i-914.pdf",
                            "description": "Application for T Nonimmigrant Status",
                        }
                    ],
                )

        row = self.db.query(FormTemplate).filter(FormTemplate.form_type == "i-914").one()
        self.assertEqual(row.name, "I-914")
        self.assertEqual(row.s3_key, "formas/i-914.pdf")
        self.assertEqual(row.original_filename, "i-914.pdf")
        self.assertEqual(row.file_size, 7)
        self.assertEqual(summary["form_templates"][0]["action"], "updated")
        self.assertEqual(fake_storage.uploads[0][0], "formas/i-914.pdf")

    def test_sync_qc_templates_rebuilds_existing_structure(self) -> None:
        checklist = QCChecklist(
            name="QC Checklist - I-765",
            description="Old",
            is_template=True,
            case_id=None,
        )
        self.db.add(checklist)
        self.db.commit()

        summary = template_sync_service.sync_qc_templates(
            self.db,
            specs=[
                {
                    "form_type": "i-765",
                    "match_token": "I-765",
                    "template": {
                        "name": "QC Checklist - I-765",
                        "description": "Updated description",
                        "parts": [
                            {
                                "code": "Part 1",
                                "name": "Part 1",
                                "questions": [
                                    {
                                        "code": "1",
                                        "description": "Question 1",
                                        "where_to_verify": "Packet",
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        )

        refreshed = self.db.query(QCChecklist).filter(QCChecklist.id == checklist.id).one()
        self.assertEqual(refreshed.description, "Updated description")
        self.assertEqual(len(refreshed.parts), 1)
        self.assertEqual(refreshed.parts[0].questions[0].description, "Question 1")
        self.assertEqual(summary["qc_templates"][0]["action"], "updated")


if __name__ == "__main__":
    unittest.main()
