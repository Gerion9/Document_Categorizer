"""add_verification_columns_to_questionnaire_answers

Revision ID: b7e9c2a4f180
Revises: a1b2c3d4e5f6
Create Date: 2026-05-04 10:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e9c2a4f180"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
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

    if not _has_column(table_name, "verification_status"):
        op.add_column(table_name, sa.Column("verification_status", sa.String(), nullable=True))
    if not _has_column(table_name, "verification_reason"):
        op.add_column(table_name, sa.Column("verification_reason", sa.Text(), nullable=True))
    if not _has_column(table_name, "verification_evidence"):
        op.add_column(table_name, sa.Column("verification_evidence", sa.Text(), nullable=True))
    if not _has_column(table_name, "verification_model"):
        op.add_column(table_name, sa.Column("verification_model", sa.String(), nullable=True))
    if not _has_column(table_name, "verified_at"):
        op.add_column(table_name, sa.Column("verified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    table_name = "questionnaire_answers"

    if _has_column(table_name, "verified_at"):
        op.drop_column(table_name, "verified_at")
    if _has_column(table_name, "verification_model"):
        op.drop_column(table_name, "verification_model")
    if _has_column(table_name, "verification_evidence"):
        op.drop_column(table_name, "verification_evidence")
    if _has_column(table_name, "verification_reason"):
        op.drop_column(table_name, "verification_reason")
    if _has_column(table_name, "verification_status"):
        op.drop_column(table_name, "verification_status")
