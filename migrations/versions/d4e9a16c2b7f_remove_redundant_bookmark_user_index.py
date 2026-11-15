"""사용자 단일 인덱스 중복을 제거한다.

Revision ID: d4e9a16c2b7f
Revises: a91c2d7e4b10
"""
from alembic import op


revision = "d4e9a16c2b7f"
down_revision = "a91c2d7e4b10"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_bookmarks_user_id", table_name="bookmarks")


def downgrade():
    op.create_index("ix_bookmarks_user_id", "bookmarks", ["user_id"], unique=False)
