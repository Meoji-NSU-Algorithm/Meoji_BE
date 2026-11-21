"""user FK 키 추가

Revision ID: 82d4628d9b03
Revises: 0fc3623be2cf
Create Date: 2026-10-03 16:35:46.248485

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '82d4628d9b03'
down_revision = '0fc3623be2cf'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_review_user_id',
            'user',
            ['user_id'],
            ['id']
        )


def downgrade():
    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.drop_constraint(
            'fk_review_user_id',
            type_='foreignkey'
        )