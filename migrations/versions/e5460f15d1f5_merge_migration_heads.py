"""merge migration heads

Revision ID: e5460f15d1f5
Revises: d5b81f3a6c27, c5e8a2f7b140
Create Date: 2026-10-30 12:50:09.328406

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e5460f15d1f5'
down_revision = ('d5b81f3a6c27', 'c5e8a2f7b140')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
