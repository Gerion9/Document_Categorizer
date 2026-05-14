"""merge_form_filling_heads_and_add_party_counts

Revision ID: f2c6b9a1d4e8
Revises: 8687172ce7fe, 6c0c0cbf6f5a
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f2c6b9a1d4e8"
down_revision: Union[str, Sequence[str], None] = ("8687172ce7fe", "6c0c0cbf6f5a")
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
    if _has_table("form_filling_jobs"):
        job_columns = _column_names("form_filling_jobs")
        with op.batch_alter_table("form_filling_jobs") as batch_op:
            if "client_field_count" not in job_columns:
                batch_op.add_column(
                    sa.Column("client_field_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
                )
            if "client_filled_count" not in job_columns:
                batch_op.add_column(
                    sa.Column("client_filled_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
                )
            if "attorney_field_count" not in job_columns:
                batch_op.add_column(
                    sa.Column("attorney_field_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
                )
            if "attorney_filled_count" not in job_columns:
                batch_op.add_column(
                    sa.Column("attorney_filled_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
                )

    if _has_table("form_filling_fields"):
        field_columns = _column_names("form_filling_fields")
        with op.batch_alter_table("form_filling_fields") as batch_op:
            if "responsible_party" not in field_columns:
                batch_op.add_column(
                    sa.Column("responsible_party", sa.String(), nullable=False, server_default=sa.text("'client'"))
                )

        op.execute(
            """
            UPDATE form_filling_fields
            SET responsible_party = 'client'
            WHERE responsible_party IS NULL OR trim(responsible_party) = ''
            """
        )

    if _has_table("form_filling_jobs"):
        op.execute(
            """
            UPDATE form_filling_jobs
            SET client_field_count = COALESCE(field_count, 0),
                client_filled_count = COALESCE(filled_count, 0),
                attorney_field_count = COALESCE(attorney_field_count, 0),
                attorney_filled_count = COALESCE(attorney_filled_count, 0)
            WHERE COALESCE(client_field_count, 0) = 0
              AND COALESCE(client_filled_count, 0) = 0
              AND COALESCE(attorney_field_count, 0) = 0
              AND COALESCE(attorney_filled_count, 0) = 0
            """
        )


def downgrade() -> None:
    if _has_table("form_filling_fields"):
        field_columns = _column_names("form_filling_fields")
        if "responsible_party" in field_columns:
            with op.batch_alter_table("form_filling_fields") as batch_op:
                batch_op.drop_column("responsible_party")

    if _has_table("form_filling_jobs"):
        job_columns = _column_names("form_filling_jobs")
        with op.batch_alter_table("form_filling_jobs") as batch_op:
            if "attorney_filled_count" in job_columns:
                batch_op.drop_column("attorney_filled_count")
            if "attorney_field_count" in job_columns:
                batch_op.drop_column("attorney_field_count")
            if "client_filled_count" in job_columns:
                batch_op.drop_column("client_filled_count")
            if "client_field_count" in job_columns:
                batch_op.drop_column("client_field_count")
