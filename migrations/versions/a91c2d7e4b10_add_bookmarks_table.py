"""사용자별 행사 북마크 테이블을 추가한다.

Revision ID: a91c2d7e4b10
Revises: fd8da9482b62
Create Date: 2026-10-06

"""
from alembic import op
import sqlalchemy as sa


revision = "a91c2d7e4b10"
down_revision = "fd8da9482b62"
branch_labels = None
depends_on = None


def upgrade():
    """bookmarks 테이블과 조회용 인덱스를 생성한다."""
    # id는 행 식별자, user_id/event_id는 회원·행사 참조, created_at은 저장 시각이다.
    # CASCADE는 회원이나 행사가 삭제될 때 연결된 북마크도 함께 지운다.
    # 복합 고유 제약은 같은 회원이 같은 행사를 중복 저장하지 못하게 한다.
    op.create_table(
        "bookmarks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], name="fk_bookmarks_event_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_bookmarks_user_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "event_id", name="uq_bookmarks_user_event"),
    )
    # 회원별 목록과 행사별 북마크 조회를 빠르게 하도록 외래 키에 인덱스를 만든다.
    with op.batch_alter_table("bookmarks", schema=None) as batch_op:
        batch_op.create_index("ix_bookmarks_event_id", ["event_id"], unique=False)
        batch_op.create_index("ix_bookmarks_user_id", ["user_id"], unique=False)


def downgrade():
    """upgrade에서 만든 인덱스와 테이블을 역순으로 제거한다."""
    with op.batch_alter_table("bookmarks", schema=None) as batch_op:
        batch_op.drop_index("ix_bookmarks_user_id")
        batch_op.drop_index("ix_bookmarks_event_id")
    op.drop_table("bookmarks")
