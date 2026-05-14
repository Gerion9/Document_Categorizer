"""add_questionnaire_answers

Revision ID: 3a4d07c8f1b2
Revises: f2c6b9a1d4e8
Create Date: 2026-03-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3a4d07c8f1b2"
down_revision: Union[str, Sequence[str], None] = "f2c6b9a1d4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa.inspect(bind).get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _has_table("questionnaire_answers"):
        op.create_table(
            "questionnaire_answers",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("case_id", sa.String(), nullable=False),
            sa.Column("question_id", sa.String(), nullable=False),
            sa.Column("value", sa.Text(), nullable=False, server_default=sa.text("''")),
            sa.Column("source", sa.String(), nullable=False, server_default=sa.text("'shared'")),
            sa.Column("form_type", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "case_id",
                "question_id",
                "form_type",
                name="uq_questionnaire_answers_case_question_form",
            ),
        )

    if not _has_index("questionnaire_answers", "ix_questionnaire_answers_case_id"):
        op.create_index(
            "ix_questionnaire_answers_case_id",
            "questionnaire_answers",
            ["case_id"],
            unique=False,
        )
    if not _has_index("questionnaire_answers", "ix_questionnaire_answers_form_type"):
        op.create_index(
            "ix_questionnaire_answers_form_type",
            "questionnaire_answers",
            ["form_type"],
            unique=False,
        )


def downgrade() -> None:
    if _has_index("questionnaire_answers", "ix_questionnaire_answers_form_type"):
        op.drop_index("ix_questionnaire_answers_form_type", table_name="questionnaire_answers")
    if _has_index("questionnaire_answers", "ix_questionnaire_answers_case_id"):
        op.drop_index("ix_questionnaire_answers_case_id", table_name="questionnaire_answers")
    if _has_table("questionnaire_answers"):
        op.drop_table("questionnaire_answers")
