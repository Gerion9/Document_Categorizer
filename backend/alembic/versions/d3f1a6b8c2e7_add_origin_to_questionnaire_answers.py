"""add_origin_to_questionnaire_answers

Revision ID: d3f1a6b8c2e7
Revises: c8a1d2e0f3b5
Create Date: 2026-05-29 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3f1a6b8c2e7"
down_revision: Union[str, Sequence[str], None] = "c8a1d2e0f3b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    table_name = "questionnaire_answers"

    if not _has_column(table_name, "origin"):
        op.add_column(table_name, sa.Column("origin", sa.Text(), nullable=True))


def downgrade() -> None:
    table_name = "questionnaire_answers"

    if _has_column(table_name, "origin"):
        op.drop_column(table_name, "origin")
