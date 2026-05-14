"""merge_questionnaire_and_scope_heads

Revision ID: a1b2c3d4e5f6
Revises: 3a4d07c8f1b2, 9d5c1a7b2e4f
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = ("3a4d07c8f1b2", "9d5c1a7b2e4f")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
