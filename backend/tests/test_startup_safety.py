import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.database import Base
from app.models import Case, QuestionnaireAnswer
from app.services.startup_validation import collect_startup_validation_report
from migrate import resolve_migration_mode


class StartupSettingsTests(unittest.TestCase):
    def test_production_defaults_disable_seeders_and_legacy_migrations(self) -> None:
        settings = Settings(
            APP_ENV="production",
            AWS_ACCESS_KEY_ID="test",
            AWS_SECRET_ACCESS_KEY="test",
            AWS_S3_BUCKET="bucket",
        )

        self.assertTrue(settings.is_production())
        self.assertFalse(settings.should_run_startup_seeders())
        self.assertFalse(settings.should_run_legacy_migrations())
        self.assertEqual(settings.startup_validation_mode(), "warn")


class MigrationModeTests(unittest.TestCase):
    def test_existing_schema_without_alembic_requires_explicit_override(self) -> None:
        self.assertEqual(
            resolve_migration_mode({"cases", "users"}, allow_existing_schema_stamp=False),
            "abort_existing_without_alembic",
        )
        self.assertEqual(
            resolve_migration_mode({"cases", "users"}, allow_existing_schema_stamp=True),
            "stamp_existing",
        )

    def test_empty_schema_is_treated_as_fresh(self) -> None:
        self.assertEqual(resolve_migration_mode(set(), allow_existing_schema_stamp=False), "fresh")


class StartupValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.Session()
        self.db.add(Case(id="case-1", name="Validation case"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_report_flags_unknown_questionnaire_answers(self) -> None:
        self.db.add(
            QuestionnaireAnswer(
                case_id="case-1",
                question_id="p999_999.unknown_field",
                value="test",
                source="form_client",
                form_type="i-914",
            )
        )
        self.db.commit()

        settings = Settings(
            APP_ENV="development",
            AWS_ACCESS_KEY_ID="test",
            AWS_SECRET_ACCESS_KEY="test",
            AWS_S3_BUCKET="bucket",
            VALIDATE_TEMPLATE_FILES_ON_STARTUP=False,
            VALIDATE_S3_ON_STARTUP=False,
            VALIDATE_QUESTIONNAIRE_ANSWERS_ON_STARTUP=True,
        )

        report = collect_startup_validation_report(self.db, settings=settings)

        self.assertEqual(report["status"], "warning")
        self.assertIn("unknown_questionnaire_answers", {issue["code"] for issue in report["warnings"]})

    def test_report_accepts_parent_question_ids_for_group_answers(self) -> None:
        self.db.add_all(
            [
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="shared.name",
                    value='{"family_name":"Doe","given_name":"Jane"}',
                    source="shared",
                    form_type="",
                ),
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="p2_4",
                    value='{"safe_city":"Houston","safe_state":"TX"}',
                    source="form_client",
                    form_type="i-914",
                ),
            ]
        )
        self.db.commit()

        settings = Settings(
            APP_ENV="development",
            AWS_ACCESS_KEY_ID="test",
            AWS_SECRET_ACCESS_KEY="test",
            AWS_S3_BUCKET="bucket",
            VALIDATE_TEMPLATE_FILES_ON_STARTUP=False,
            VALIDATE_S3_ON_STARTUP=False,
            VALIDATE_QUESTIONNAIRE_ANSWERS_ON_STARTUP=True,
        )

        report = collect_startup_validation_report(self.db, settings=settings)

        self.assertNotIn("unknown_questionnaire_answers", {issue["code"] for issue in report["warnings"]})

    def test_report_excludes_temporarily_disabled_i914a_assets(self) -> None:
        settings = Settings(
            APP_ENV="development",
            AWS_ACCESS_KEY_ID="test",
            AWS_SECRET_ACCESS_KEY="test",
            AWS_S3_BUCKET="bucket",
            VALIDATE_TEMPLATE_FILES_ON_STARTUP=True,
            VALIDATE_S3_ON_STARTUP=False,
            VALIDATE_QUESTIONNAIRE_ANSWERS_ON_STARTUP=False,
        )

        report = collect_startup_validation_report(self.db, settings=settings)
        reported_codes = {
            issue["code"]
            for issue in [*report["warnings"], *report["errors"]]
        }

        self.assertNotIn("missing_blank_pdf_templates", reported_codes)
        self.assertNotIn("form_registry_missing_assets", reported_codes)


if __name__ == "__main__":
    unittest.main()
