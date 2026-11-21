"""feat: 전국 축제 테이블 여섯 개 추가

Revision ID: 62d4e8a91b03
Revises: 3e08a9570f0c
"""

from alembic import op
import sqlalchemy as sa

revision = "62d4e8a91b03"
down_revision = "3e08a9570f0c"
branch_labels = None
depends_on = None

# categories/sidos는 FK 기준값이므로 events를 저장하기 전에 반드시 채운다.
# 태그 목록은 app/domains/tour/sync_service.py의 TAG_KEYWORDS와 동일해야 소개글 매칭이 가능하다.
CATEGORIES = [("축제", 1), ("전시", 2), ("공연", 3), ("체험", 4), ("계절행사", 5)]
SIDOS = [
    ("11", "서울특별시", "서울", 1),
    ("41", "경기도", "경기", 2),
    ("26", "부산광역시", "부산", 3),
    ("51", "강원특별자치도", "강원", 4),
    ("44", "충청남도", "충남", 5),
    ("28", "인천광역시", "인천", 6),
    ("27", "대구광역시", "대구", 7),
    ("30", "대전광역시", "대전", 8),
    ("31", "울산광역시", "울산", 9),
    ("36", "세종특별자치시", "세종", 10),
    ("43", "충청북도", "충북", 11),
    ("52", "전북특별자치도", "전북", 12),
    ("12", "전남광주통합특별시", "전남광주", 13),
    ("47", "경상북도", "경북", 14),
    ("48", "경상남도", "경남", 15),
    ("50", "제주특별자치도", "제주", 16),
]
TAGS = ("불꽃놀이", "푸드트럭", "야간", "체험", "가족", "공연", "전시", "음악", "꽃", "먹거리")


def upgrade():
    # 1. 카테고리·지역 기준 테이블. 지역 코드는 숫자 ID가 아닌 CHAR(2)다.
    op.create_table("categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False, unique=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("sidos",
        sa.Column("code", sa.CHAR(2), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("short_name", sa.String(10), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))

    # 2. 행사 본문. 모든 숫자형 ID/FK는 INT이고, contentid는 재수집 중복 방지용 UNIQUE다.
    op.create_table("events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tour_content_id", sa.String(20), nullable=False, unique=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("sido_code", sa.CHAR(2), sa.ForeignKey("sidos.code"), nullable=False),
        sa.Column("lcls_code", sa.String(10)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("play_time", sa.String(500)),
        sa.Column("venue_name", sa.String(300)),
        sa.Column("address", sa.String(300)),
        sa.Column("address_detail", sa.String(300)),
        sa.Column("latitude", sa.Numeric(10, 7)),
        sa.Column("longitude", sa.Numeric(10, 7)),
        sa.Column("image_url", sa.String(500)),
        sa.Column("thumbnail_url", sa.String(500)),
        # 실제 usetimefestival이 500자를 넘기도 하므로 원문은 TEXT로 보관한다.
        sa.Column("fee_text", sa.Text()),
        sa.Column("price", sa.Integer()),
        sa.Column("is_free", sa.Boolean()),
        sa.Column("organizer", sa.String(300)),
        sa.Column("contact_phone", sa.String(300)),
        sa.Column("homepage_url", sa.String(1000)),
        sa.Column("is_permanent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tour_modified_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("start_date <= end_date", name="ck_events_date_range"))
    # category_id/sido_code는 필터에, 날짜 쌍은 기간 검색에 사용한다.
    op.create_index("ix_events_category_id", "events", ["category_id"])
    op.create_index("ix_events_sido_code", "events", ["sido_code"])
    op.create_index("idx_events_dates", "events", ["start_date", "end_date"])

    # 3. 검색 태그와 행사 연결. 복합 PK로 같은 태그를 중복 연결하지 않는다.
    op.create_table("tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), nullable=False, unique=True))
    op.create_table("event_tags",
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True))
    op.create_index("ix_event_tags_tag_id", "event_tags", ["tag_id"])

    # 4. 행사별·날짜별 조회수. 상세 조회 기능이 구현될 때 이 테이블을 증가시킨다.
    op.create_table("event_daily_views",
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("view_date", sa.Date(), primary_key=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_event_daily_views_view_date", "event_daily_views", ["view_date"])

    # 시드 데이터는 빈 신규 테이블에 한 번만 삽입한다. 운영에서 별도 seed.sql을
    # 실행하면 중복되므로 README의 db upgrade만 사용한다.
    connection = op.get_bind()
    connection.execute(sa.text("INSERT INTO categories (name, sort_order) VALUES (:name, :sort_order)"),
                       [{"name": name, "sort_order": order} for name, order in CATEGORIES])
    connection.execute(sa.text("INSERT INTO sidos (code, name, short_name, sort_order) VALUES (:code, :name, :short_name, :sort_order)"),
                       [{"code": code, "name": name, "short_name": short, "sort_order": order}
                        for code, name, short, order in SIDOS])
    connection.execute(sa.text("INSERT INTO tags (name) VALUES (:name)"),
                       [{"name": name} for name in TAGS])

    # 이 개발 DB는 이전 관광 테이블을 만들지 않는다. 기존 DB는 초기화 후 적용한다.


def downgrade():
    # 자식 테이블을 먼저 제거해야 FK 제약에 걸리지 않는다.
    # downgrade는 이번 마이그레이션에서 만든 행사 데이터도 삭제한다.
    op.drop_table("event_daily_views")
    op.drop_table("event_tags")
    op.drop_table("tags")
    op.drop_table("events")
    op.drop_table("sidos")
    op.drop_table("categories")
