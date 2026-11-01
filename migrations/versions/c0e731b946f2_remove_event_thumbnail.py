"""Use original event images and remove thumbnail_url."""
from alembic import op
import sqlalchemy as sa

revision = "c0e731b946f2"
down_revision = "a7c3e1d94b52"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("events", "thumbnail_url")


def downgrade():
    op.add_column("events", sa.Column("thumbnail_url", sa.String(500), nullable=True))
