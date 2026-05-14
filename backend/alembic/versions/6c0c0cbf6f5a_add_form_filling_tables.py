"""add_form_filling_tables

Revision ID: 6c0c0cbf6f5a
Revises: da9eaacb2416
Create Date: 2026-03-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6c0c0cbf6f5a"
down_revision: Union[str, Sequence[str], None] = "da9eaacb2416"
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
    if not _has_table("form_filling_jobs"):
        op.create_table(
            "form_filling_jobs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("case_id", sa.String(), nullable=False),
            sa.Column("form_type", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=True),
            sa.Column("phase", sa.String(), nullable=True),
            sa.Column("progress_pct", sa.Float(), nullable=True),
            sa.Column("original_pdf_path", sa.String(), nullable=True),
            sa.Column("filled_pdf_path", sa.String(), nullable=True),
            sa.Column("field_count", sa.Integer(), nullable=True),
            sa.Column("filled_count", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("form_filling_jobs", "ix_form_filling_jobs_case_id"):
        op.create_index("ix_form_filling_jobs_case_id", "form_filling_jobs", ["case_id"], unique=False)
    if not _has_index("form_filling_jobs", "ix_form_filling_jobs_status"):
        op.create_index("ix_form_filling_jobs_status", "form_filling_jobs", ["status"], unique=False)

    if not _has_table("form_filling_fields"):
        op.create_table(
            "form_filling_fields",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("job_id", sa.String(), nullable=False),
            sa.Column("field_name", sa.String(), nullable=False),
            sa.Column("field_label", sa.String(), nullable=True),
            sa.Column("field_type", sa.String(), nullable=True),
            sa.Column("questionnaire_item_id", sa.String(), nullable=True),
            sa.Column("questionnaire_field_id", sa.String(), nullable=True),
            sa.Column("questionnaire_option_value", sa.String(), nullable=True),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("extracted_value", sa.Text(), nullable=True),
            sa.Column("confidence", sa.String(), nullable=True),
            sa.Column("evidence_source", sa.Text(), nullable=True),
            sa.Column("manually_corrected", sa.Boolean(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["job_id"], ["form_filling_jobs.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _has_index("form_filling_fields", "ix_form_filling_fields_job_id"):
        op.create_index("ix_form_filling_fields_job_id", "form_filling_fields", ["job_id"], unique=False)
    if not _has_index("form_filling_fields", "ix_form_filling_fields_field_name"):
        op.create_index("ix_form_filling_fields_field_name", "form_filling_fields", ["field_name"], unique=False)


def downgrade() -> None:
    if _has_index("form_filling_fields", "ix_form_filling_fields_field_name"):
        op.drop_index("ix_form_filling_fields_field_name", table_name="form_filling_fields")
    if _has_index("form_filling_fields", "ix_form_filling_fields_job_id"):
        op.drop_index("ix_form_filling_fields_job_id", table_name="form_filling_fields")
    if _has_table("form_filling_fields"):
        op.drop_table("form_filling_fields")

    if _has_index("form_filling_jobs", "ix_form_filling_jobs_status"):
        op.drop_index("ix_form_filling_jobs_status", table_name="form_filling_jobs")
    if _has_index("form_filling_jobs", "ix_form_filling_jobs_case_id"):
        op.drop_index("ix_form_filling_jobs_case_id", table_name="form_filling_jobs")
    if _has_table("form_filling_jobs"):
        op.drop_table("form_filling_jobs")
