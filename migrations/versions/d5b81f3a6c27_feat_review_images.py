"""Add review images (storage keys as JSON)."""
from alembic import op
import sqlalchemy as sa

revision = "d5b81f3a6c27"
down_revision = "c0e731b946f2"
branch_labels = None
depends_on = None


def upgrade():
    # 기존 리뷰는 NULL로 두고 응답에서 빈 목록으로 내려준다. 기본값을 채우는 데이터 이동이 필요 없다.
    op.add_column("review", sa.Column("images", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("review", "images")
