"""add_field_origins_to_questionnaire_answers

Revision ID: e4a2b7c9d1f0
Revises: d3f1a6b8c2e7
Create Date: 2026-06-01 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a2b7c9d1f0"
down_revision: Union[str, Sequence[str], None] = "d3f1a6b8c2e7"
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
    if not _has_column(table_name, "field_origins"):
        op.add_column(table_name, sa.Column("field_origins", sa.Text(), nullable=True))


def downgrade() -> None:
    table_name = "questionnaire_answers"
    if _has_column(table_name, "field_origins"):
        op.drop_column(table_name, "field_origins")
