"""add_deleted_at_to_pages

Revision ID: 8687172ce7fe
Revises: da9eaacb2416
Create Date: 2026-03-18 14:17:44.719942

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8687172ce7fe'
down_revision: Union[str, Sequence[str], None] = 'da9eaacb2416'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_index("idx_pages_deleted_at", "pages", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("idx_pages_deleted_at", table_name="pages")
    op.drop_column("pages", "deleted_at")
