"""add_warnings_to_form_filling_jobs

Revision ID: c8a1d2e0f3b5
Revises: b7e9c2a4f180
Create Date: 2026-05-12 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8a1d2e0f3b5"
down_revision: Union[str, Sequence[str], None] = "b7e9c2a4f180"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    return any(col["name"] == column_name for col in inspector.get_columns(table_name))


def upgrade() -> None:
    table_name = "form_filling_jobs"
    if not _has_column(table_name, "warnings"):
        op.add_column(
            table_name,
            sa.Column(
                "warnings",
                sa.JSON(),
                nullable=True,
                server_default=sa.text("'[]'"),
            ),
        )
        op.execute(
            f"UPDATE {table_name} SET warnings = '[]' WHERE warnings IS NULL"
        )


def downgrade() -> None:
    table_name = "form_filling_jobs"
    if _has_column(table_name, "warnings"):
        op.drop_column(table_name, "warnings")
