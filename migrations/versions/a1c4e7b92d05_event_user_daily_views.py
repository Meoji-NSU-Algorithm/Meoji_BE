"""Count repeated event detail views once per user per day."""
from alembic import op
import sqlalchemy as sa

revision = "a1c4e7b92d05"
down_revision = "c7d1e93a5f20"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_user_daily_views",
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("view_date", sa.Date, primary_key=True),
    )
    op.create_index("ix_event_user_daily_views_event_id", "event_user_daily_views", ["event_id"])


def downgrade():
    op.drop_table("event_user_daily_views")
