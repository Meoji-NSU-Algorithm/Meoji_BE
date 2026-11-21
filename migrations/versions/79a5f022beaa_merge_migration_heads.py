"""merge migration heads

Revision ID: 79a5f022beaa
Revises: 82d4628d9b03, 8b4e2d7c19a0
Create Date: 2026-10-04 15:47:24.420665

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '79a5f022beaa'
down_revision = ('82d4628d9b03', '8b4e2d7c19a0')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
