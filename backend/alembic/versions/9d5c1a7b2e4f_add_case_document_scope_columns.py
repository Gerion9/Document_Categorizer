"""add_case_document_scope_columns

Revision ID: 9d5c1a7b2e4f
Revises: f2c6b9a1d4e8
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d5c1a7b2e4f"
down_revision: Union[str, Sequence[str], None] = "f2c6b9a1d4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in sa.inspect(bind).get_table_names()


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_table("cases"):
        return

    case_columns = _column_names("cases")
    with op.batch_alter_table("cases") as batch_op:
        if "form_filling_source_document_ids" not in case_columns:
            batch_op.add_column(
                sa.Column("form_filling_source_document_ids", sa.JSON(), nullable=True)
            )
        if "qc_checklist_source_document_ids" not in case_columns:
            batch_op.add_column(
                sa.Column("qc_checklist_source_document_ids", sa.JSON(), nullable=True)
            )


def downgrade() -> None:
    if not _has_table("cases"):
        return

    case_columns = _column_names("cases")
    with op.batch_alter_table("cases") as batch_op:
        if "qc_checklist_source_document_ids" in case_columns:
            batch_op.drop_column("qc_checklist_source_document_ids")
        if "form_filling_source_document_ids" in case_columns:
            batch_op.drop_column("form_filling_source_document_ids")
