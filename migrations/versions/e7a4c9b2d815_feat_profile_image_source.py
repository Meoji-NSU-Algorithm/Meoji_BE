"""Add user profile image source and custom profile image key."""
from alembic import op
import sqlalchemy as sa

revision = "e7a4c9b2d815"
down_revision = "371612cb106c"
branch_labels = None
depends_on = None


def upgrade():
    # 기존 유저는 server_default로 'kakao'가 채워져 지금처럼 카카오 사진이 보인다. 기존 profile_image 컬럼은 그대로 둔다.
    op.add_column("user", sa.Column("profile_image_source", sa.String(length=10), nullable=False, server_default="kakao"))
    op.add_column("user", sa.Column("custom_profile_image_key", sa.String(length=100), nullable=True))


def downgrade():
    op.drop_column("user", "custom_profile_image_key")
    op.drop_column("user", "profile_image_source")
