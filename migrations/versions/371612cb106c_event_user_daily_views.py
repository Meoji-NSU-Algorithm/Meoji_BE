"""사용자별 하루 1회 상세 조회 기록 (조회수 중복 집계 방지)

Revision ID: 371612cb106c
Revises: b8f24d671a90
"""
from alembic import op
import sqlalchemy as sa

revision = "371612cb106c"
down_revision = "b8f24d671a90"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_user_daily_views",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("view_date", sa.Date, primary_key=True),
    )


def downgrade():
    op.drop_table("event_user_daily_views")
