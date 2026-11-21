"""review 테이블 추가

Revision ID: 12514c462a23
Revises: 3e08a9570f0c
Create Date: 2026-09-27 19:30:26.034408

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
"""review 테이블 추가

Revision ID: 12514c462a23
Revises: 3e08a9570f0c
Create Date: 2026-09-27 19:30:26.034408

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '12514c462a23'
down_revision = '3e08a9570f0c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'review',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tour_content_id', sa.Integer(), nullable=False),
        sa.Column('rating', sa.SmallInteger(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            'rating >= 1 AND rating <= 5',
            name='ck_review_rating'
        ),
        sa.PrimaryKeyConstraint('id')
    )

    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_review_tour_content_id'),
            ['tour_content_id'],
            unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_review_user_id'),
            ['user_id'],
            unique=False
        )


def downgrade():
    with op.batch_alter_table('review', schema=None) as batch_op:
        batch_op.drop_index(
            batch_op.f('ix_review_user_id')
        )
        batch_op.drop_index(
            batch_op.f('ix_review_tour_content_id')
        )

    op.drop_table('review')
