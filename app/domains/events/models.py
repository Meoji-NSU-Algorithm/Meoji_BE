# 참조 ERD에서 담당하는 여섯 테이블의 SQLAlchemy 모델을 정의한다.
# 파일 이름은 기존 import 경로를 유지하기 위해 tour_content.py로 두었다.
# 행사·태그·일별 조회수의 숫자형 PK/FK는 모두 db.Integer(MySQL INT)다.

from app.core.extensions import db


class Category(db.Model):
    # 홈/목록의 카테고리 기준값. TourAPI lclsSystm3의 변환은 서비스에서 한다.
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)  # 내부 카테고리 ID
    name = db.Column(db.String(20), nullable=False, unique=True)  # 축제/전시/공연/체험/계절행사
    sort_order = db.Column(db.Integer, nullable=False, default=0)  # 화면 표시 순서


class Sido(db.Model):
    # 지역 필터의 기준값. TourAPI의 lDongRegnCd 앞 두 자리와 연결한다.
    __tablename__ = "sidos"
    code = db.Column(db.CHAR(2), primary_key=True)  # 지역 식별 코드라 INT로 바꾸지 않음
    name = db.Column(db.String(20), nullable=False)  # 정식 명칭
    short_name = db.Column(db.String(10), nullable=False)  # 필터 칩에 표시할 짧은 명칭
    sort_order = db.Column(db.Integer, nullable=False, default=0)  # 지역 필터 표시 순서


class Event(db.Model):
    # 전국 축제/공연/전시 등의 행사 한 건. TourAPI contentid로 중복 저장을 막는다.
    __tablename__ = "events"
    id = db.Column(db.Integer, primary_key=True)  # 서비스 내부 행사 ID
    tour_content_id = db.Column(db.String(20), nullable=False, unique=True)  # TourAPI contentid
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False, index=True)  # 카테고리 FK
    sido_code = db.Column(db.CHAR(2), db.ForeignKey("sidos.code"), nullable=False, index=True)  # 지역 FK
    lcls_code = db.Column(db.String(10))  # API 원본 lclsSystm3
    title = db.Column(db.String(200), nullable=False)  # 행사명
    description = db.Column(db.Text)  # detailCommon2의 overview
    start_date = db.Column(db.Date, nullable=False)  # 행사 시작일
    end_date = db.Column(db.Date, nullable=False)  # 행사 종료일
    play_time = db.Column(db.String(500))  # 운영 시간 안내
    venue_name = db.Column(db.String(300))  # eventplace
    address = db.Column(db.String(300))  # addr1
    address_detail = db.Column(db.String(300))  # addr2
    latitude = db.Column(db.Numeric(10, 7))  # mapy: 위도
    longitude = db.Column(db.Numeric(10, 7))  # mapx: 경도
    image_url = db.Column(db.String(500))  # firstimage: 상세 대표 이미지
    thumbnail_url = db.Column(db.String(500))  # firstimage2: 카드 썸네일
    fee_text = db.Column(db.Text)  # API 요금 원문: 실제 응답이 500자를 넘을 수 있음
    price = db.Column(db.Integer)  # 요금에서 추출한 대표 금액(원)
    is_free = db.Column(db.Boolean)  # 요금 판단 불가 시 NULL
    organizer = db.Column(db.String(300))  # sponsor1: 주최
    contact_phone = db.Column(db.String(300))  # tel: 문의 전화
    homepage_url = db.Column(db.String(1000))  # TourAPI 문구·HTML을 제거한 홈페이지 URL 하나
    is_permanent = db.Column(db.Boolean, nullable=False, default=False)  # 기간 90일 초과 여부
    view_count = db.Column(db.Integer, nullable=False, default=0)  # 누적 조회수; 수집 시 초기화 안 함
    tour_modified_at = db.Column(db.DateTime)  # API modifiedtime
    # 생성 시각은 DB가 채우고, 수정 시각은 ORM UPDATE 때 DB 현재 시각으로 갱신한다.
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, nullable=False, server_default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())

    # 기간 검색용 복합 인덱스와 역전된 행사 기간 방지 제약.
    __table_args__ = (
        db.Index("idx_events_dates", "start_date", "end_date"),
        db.CheckConstraint("start_date <= end_date", name="ck_events_date_range"),
    )

    category = db.relationship("Category")  # category_id로 분류 행 접근
    sido = db.relationship("Sido")  # sido_code로 지역 행 접근
    tags = db.relationship("Tag", secondary="event_tags", back_populates="events")  # 행사 ↔ 태그 다대다
    daily_views = db.relationship("EventDailyView", cascade="all, delete-orphan", passive_deletes=True)  # 행사 삭제 시 집계 삭제


class Tag(db.Model):
    # 소개글에서 추출해 검색에 사용하는 사전 키워드.
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)  # 태그 ID
    name = db.Column(db.String(50), nullable=False, unique=True)  # 중복 키워드 방지
    events = db.relationship("Event", secondary="event_tags", back_populates="tags")  # 연결된 행사


class EventTag(db.Model):
    # 행사와 태그의 N:M 연결. 두 FK가 복합 PK라 같은 연결은 한 번만 저장된다.
    __tablename__ = "event_tags"
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)  # 행사 삭제 시 연결 삭제
    tag_id = db.Column(db.Integer, db.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True)  # 태그 검색용 인덱스


class EventDailyView(db.Model):
    # 행사 상세 조회수를 날짜별로 저장할 테이블. 수집 서비스는 이 값을 수정하지 않는다.
    __tablename__ = "event_daily_views"
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)  # 행사 FK
    view_date = db.Column(db.Date, primary_key=True, index=True)  # 날짜별 한 행
    view_count = db.Column(db.Integer, nullable=False, default=0)  # 그날 조회수
