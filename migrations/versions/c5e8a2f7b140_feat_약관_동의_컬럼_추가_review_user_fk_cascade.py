"""feat 약관 동의 컬럼 추가, review user FK cascade

Revision ID: c5e8a2f7b140
Revises: a7c3e1d94b52
Create Date: 2026-10-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c5e8a2f7b140'
down_revision = 'a7c3e1d94b52'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('terms_agreed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('privacy_agreed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('marketing_agreed', sa.Boolean(), server_default=sa.text('0'), nullable=False))
        batch_op.add_column(sa.Column('marketing_agreed_at', sa.DateTime(), nullable=True))

    # 회원 탈퇴 시 DB가 리뷰를 함께 삭제하도록 FK를 ON DELETE CASCADE로 다시 만든다.
    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.drop_constraint('fk_review_user_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_review_user_id', 'user', ['user_id'], ['id'], ondelete='CASCADE')


def downgrade():
    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.drop_constraint('fk_review_user_id', type_='foreignkey')
        batch_op.create_foreign_key('fk_review_user_id', 'user', ['user_id'], ['id'])

    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('marketing_agreed_at')
        batch_op.drop_column('marketing_agreed')
        batch_op.drop_column('privacy_agreed_at')
        batch_op.drop_column('terms_agreed_at')
