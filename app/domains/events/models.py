"""행사와 관련 기준 데이터(카테고리·시도·태그·일별 조회수)의 ORM 모델.

숫자형 PK/FK는 모두 MySQL INT(db.Integer)를 사용한다.
"""

from app.core.extensions import db


class Category(db.Model):
    """행사 카테고리 기준값. TourAPI lclsSystm3와의 매핑은 tour.sync_service가 한다."""

    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False, unique=True)  # 축제/전시/공연/체험/계절행사
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class Sido(db.Model):
    """지역 필터 기준값. TourAPI lDongRegnCd의 앞 두 자리와 대응한다."""

    __tablename__ = "sidos"
    code = db.Column(db.CHAR(2), primary_key=True)  # 지역 식별 코드라 INT로 바꾸지 않음
    name = db.Column(db.String(20), nullable=False)
    short_name = db.Column(db.String(10), nullable=False)  # 필터 칩 표시용
    sort_order = db.Column(db.Integer, nullable=False, default=0)


class Event(db.Model):
    """행사 한 건. TourAPI contentid의 unique 제약으로 중복 저장을 막는다."""

    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)
    tour_content_id = db.Column(db.String(20), nullable=False, unique=True)  # TourAPI contentid
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)
    sido_code = db.Column(db.CHAR(2), db.ForeignKey("sidos.code"), nullable=False, index=True)
    lcls_code = db.Column(db.String(10))  # API 원본 lclsSystm3
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)  # detailCommon2의 overview
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    play_time = db.Column(db.String(500))
    venue_name = db.Column(db.String(300))  # eventplace
    address = db.Column(db.String(300))  # addr1
    address_detail = db.Column(db.String(300))  # addr2
    latitude = db.Column(db.Numeric(10, 7))  # mapy: 위도
    longitude = db.Column(db.Numeric(10, 7))  # mapx: 경도
    image_url = db.Column(db.String(500))  # firstimage: 상세 대표 이미지
    thumbnail_url = db.Column(db.String(500))  # firstimage2: 카드 썸네일
    fee_text = db.Column(db.Text)  # 요금 원문. 응답이 500자를 넘을 수 있어 Text
    price = db.Column(db.Integer)  # 원 단위 대표 금액(요금 문구 중 최소 금액)
    is_free = db.Column(db.Boolean)  # 요금을 판단할 수 없으면 NULL
    organizer = db.Column(db.String(300))  # sponsor1: 주최
    contact_phone = db.Column(db.String(300))  # tel: 문의 전화
    homepage_url = db.Column(db.String(1000))  # 원본 문구·HTML을 제거한 URL 하나
    is_permanent = db.Column(db.Boolean, nullable=False, default=False)  # 기간 90일 초과(상설) 여부
    view_count = db.Column(db.Integer, nullable=False, default=0)  # 누적 조회수. 재수집해도 덮어쓰지 않는다
    tour_modified_at = db.Column(db.DateTime)  # API modifiedtime
    # created_at/updated_at은 DB 현재 시각을 사용하며, updated_at은 ORM UPDATE마다 갱신된다.
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    # 기간 겹침 검색용 인덱스. CHECK는 시작일이 종료일보다 늦은 데이터를 막는다.
    __table_args__ = (
        db.Index("idx_events_dates", "start_date", "end_date"),
        db.CheckConstraint("start_date <= end_date", name="ck_events_date_range"),
    )

    category = db.relationship("Category")
    sido = db.relationship("Sido")
    tags = db.relationship("Tag", secondary="event_tags", back_populates="events")
    daily_views = db.relationship("EventDailyView", cascade="all, delete-orphan", passive_deletes=True)


class Tag(db.Model):
    """소개글에서 추출해 검색에 쓰는 사전 키워드."""

    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    events = db.relationship("Event", secondary="event_tags", back_populates="tags")


class EventTag(db.Model):
    """행사와 태그의 N:M 연결. 두 FK가 복합 PK라 같은 연결은 한 번만 저장된다."""

    __tablename__ = "event_tags"
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)


class EventDailyView(db.Model):
    """행사 상세 조회수의 일별 집계. 수집 서비스는 이 테이블을 수정하지 않는다."""

    __tablename__ = "event_daily_views"
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    view_date = db.Column(db.Date, primary_key=True, index=True)
    view_count = db.Column(db.Integer, nullable=False, default=0)
