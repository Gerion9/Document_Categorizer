"""baseline_existing_tables

Revision ID: da9eaacb2416
Revises: 
Create Date: 2026-03-13 13:57:09.822520

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'da9eaacb2416'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('created_by', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_cases_created_by_users', 'cases', 'users', ['created_by'], ['id'])


def downgrade() -> None:
    op.drop_constraint('fk_cases_created_by_users', 'cases', type_='foreignkey')
    op.drop_column('cases', 'created_by')
