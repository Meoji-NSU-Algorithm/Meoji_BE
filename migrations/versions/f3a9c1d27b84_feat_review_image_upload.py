"""Track unattached review image uploads for cleanup."""
from alembic import op
import sqlalchemy as sa

revision = "f3a9c1d27b84"
down_revision = "e5460f15d1f5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_image_upload",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_review_image_upload_user_id", "review_image_upload", ["user_id"])
    op.create_index("ix_review_image_upload_created_at", "review_image_upload", ["created_at"])


def downgrade():
    op.drop_table("review_image_upload")
