import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Case, QuestionnaireAnswer
from app.services import questionnaire_service


def _utc_at(seconds: int) -> datetime:
    return datetime(2026, 4, 15, tzinfo=timezone.utc) + timedelta(seconds=seconds)


class QuestionnaireServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.db = self.Session()
        self.db.add(Case(id="case-1", name="Questionnaire case"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def test_get_answers_prefers_latest_shared_duplicate_row(self) -> None:
        self.db.add_all(
            [
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="shared.country_of_citizenship",
                    value='[{"country": "Peru"}]',
                    source="shared",
                    form_type=None,
                    created_at=_utc_at(1),
                    updated_at=_utc_at(1),
                ),
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="shared.country_of_citizenship",
                    value='[{"country": "Ecuador"}]',
                    source="shared",
                    form_type=None,
                    created_at=_utc_at(5),
                    updated_at=_utc_at(5),
                ),
            ]
        )
        self.db.commit()

        answers = questionnaire_service.get_answers(self.db, "case-1")

        self.assertEqual(
            answers["shared.country_of_citizenship"],
            [{"country": "Ecuador"}],
        )

    def test_save_answers_cleans_legacy_shared_duplicates(self) -> None:
        self.db.add_all(
            [
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="shared.address_history_last_five_years",
                    value="[]",
                    source="shared",
                    form_type=None,
                    created_at=_utc_at(1),
                    updated_at=_utc_at(1),
                ),
                QuestionnaireAnswer(
                    case_id="case-1",
                    question_id="shared.address_history_last_five_years",
                    value='[{"street_number_name": "Old address", "city": "Old city", "country": "Old country"}]',
                    source="shared",
                    form_type=None,
                    created_at=_utc_at(3),
                    updated_at=_utc_at(3),
                ),
            ]
        )
        self.db.commit()

        questionnaire_service.save_answers(
            self.db,
            "case-1",
            [
                {
                    "question_id": "shared.address_history_last_five_years",
                    "value": [
                        {
                            "street_number_name": "123 Main St",
                            "city": "Quito",
                            "country": "Ecuador",
                        }
                    ],
                    "source": "shared",
                }
            ],
        )

        rows = (
            self.db.query(QuestionnaireAnswer)
            .filter(
                QuestionnaireAnswer.case_id == "case-1",
                QuestionnaireAnswer.question_id == "shared.address_history_last_five_years",
            )
            .all()
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].form_type, "")

        answers = questionnaire_service.get_answers(self.db, "case-1")
        self.assertEqual(
            answers["shared.address_history_last_five_years"],
            [
                {
                    "street_number_name": "123 Main St",
                    "city": "Quito",
                    "country": "Ecuador",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
