"""저장된 행사의 목록·월간 순위·상세 조회와 조회수 기록을 담당한다.

TourAPI 수집(tour.sync_service)과는 분리되어 DB에 저장된 데이터만 읽는다.
"""

from calendar import monthrange
from datetime import date, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Category, Event, EventDailyView, Sido, Tag


def _contains_keyword(value: str | None) -> str | None:
    """검색어를 LIKE 부분 일치 패턴으로 바꾼다. 공백뿐이거나 None이면 None을 반환한다."""
    text = (value or "").strip()
    if not text:
        return None
    # 사용자가 입력한 %, _, \\가 LIKE 와일드카드로 해석되지 않도록 이스케이프한다.
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_categories() -> list[Category]:
    """카테고리 전체를 표시 순서대로 반환한다. 같은 순서값은 ID로 정렬한다."""
    statement = select(Category).order_by(Category.sort_order, Category.id)
    return db.session.scalars(statement).all()

def list_sidos() -> list[Sido]:
    """시도 전체를 표시 순서대로 반환한다. 기준값은 마이그레이션이 시드한다."""
    statement = select(Sido).order_by(Sido.sort_order, Sido.code)
    return db.session.scalars(statement).all()

def monthly_top(query: dict, today: date | None = None) -> dict:
    """월간 조회수 상위 행사를 반환한다.

    조회 기록이 size보다 적으면 종료일이 가까운 진행 중 행사로 채운다(monthly_views=0).

    Args:
        query: month(None이면 KST 기준 이번 달 1일)와 size.
        today: 기준 날짜. 생략하면 KST 오늘이며 테스트에서 주입한다.

    Returns:
        month(YYYY-MM)와 events(`{"event", "monthly_views"}` 목록). 대상이 없으면 빈 목록.
    """
    current_date = today or datetime.now(KST).date()
    month = query["month"] or current_date.replace(day=1)
    month_end = date(month.year, month.month, monthrange(month.year, month.month)[1])
    monthly_views = (
        select(
            EventDailyView.event_id.label("event_id"),
            func.sum(EventDailyView.view_count).label("monthly_views"),
        )
        .where(
            EventDailyView.view_date >= month,
            EventDailyView.view_date <= month_end,
        )
        .group_by(EventDailyView.event_id)
        .having(func.sum(EventDailyView.view_count) > 0)
        .subquery()
    )

    # 이미 끝난 행사는 제외한다. 월간 합계가 같으면 ID 내림차순으로 순서를 고정한다.
    statement = (
        select(Event, monthly_views.c.monthly_views)
        .join(monthly_views, monthly_views.c.event_id == Event.id)
        .options(joinedload(Event.category), joinedload(Event.sido))
        .where(Event.end_date >= current_date)
        .order_by(monthly_views.c.monthly_views.desc(), Event.id.desc())
        .limit(query["size"])
    )
    rows = [(event, views) for event, views in db.session.execute(statement).all()]
    if len(rows) < query["size"]:
        # 조회 기록이 적어도 빈 응답이 되지 않도록 순위에 없는 행사로 채운다.
        ranked_ids = [event.id for event, _ in rows]
        recommendations = db.session.scalars(
            select(Event)
            .options(joinedload(Event.category), joinedload(Event.sido))
            .where(Event.end_date >= current_date, Event.id.not_in(ranked_ids))
            .order_by(Event.end_date.asc(), Event.start_date.asc(), Event.id.asc())
            .limit(query["size"] - len(rows))
        ).all()
        rows.extend((event, 0) for event in recommendations)
    return {
        "month": f"{month.year:04d}-{month.month:02d}",
        "events": [
            {"event": event, "monthly_views": views}
            for event, views in rows
        ],
    }

def list_events(query: dict) -> dict:
    """종료되지 않은 행사를 조건에 맞게 검색해 한 페이지를 반환한다.

    Args:
        query: 스키마로 검증된 필터·검색어·sort·page·size.

    Returns:
        total_count(필터 전체 건수), page, size, events. 범위를 넘은 페이지는 events가 빈 목록이다.
    """
    # 지난 행사는 DB에 보관하되 목록에서만 숨긴다. 종료일이 오늘이면 아직 표시한다.
    conditions = [Event.end_date >= datetime.now(KST).date()]
    if query["category_id"] is not None:
        conditions.append(Event.category_id == query["category_id"])
    if query["sido_code"] is not None:
        conditions.append(Event.sido_code == query["sido_code"])
    if query["is_free"] is not None:
        conditions.append(Event.is_free == query["is_free"])
    if query["start_date"] is not None:
        conditions.append(Event.end_date >= query["start_date"])
    if query["end_date"] is not None:
        conditions.append(Event.start_date <= query["end_date"])

    # q는 제목·장소·태그 중 한 곳이라도 일치하면 포함하는 통합 검색이다.
    keyword = _contains_keyword(query["q"])
    if keyword:
        conditions.append(
            or_(
                Event.title.ilike(keyword, escape="\\"),
                Event.venue_name.ilike(keyword, escape="\\"),
                Event.tags.any(Tag.name.ilike(keyword, escape="\\")),
            )
        )

    # 세부 검색(title/venue/tag)은 지정한 필드만 검사하며 다른 조건과 AND로 결합한다.
    title_keyword = _contains_keyword(query["title"])
    if title_keyword:
        conditions.append(Event.title.ilike(title_keyword, escape="\\"))
    venue_keyword = _contains_keyword(query["venue"])
    if venue_keyword:
        conditions.append(Event.venue_name.ilike(venue_keyword, escape="\\"))
    tag_keyword = _contains_keyword(query["tag"])
    if tag_keyword:
        # 태그 테이블을 JOIN하면 여러 태그가 맞을 때 행사가 중복되어 total_count가
        # 부풀기 때문에 EXISTS(any)로 확인한다. q의 태그 검색도 같은 이유다.
        conditions.append(Event.tags.any(Tag.name.ilike(tag_keyword, escape="\\")))

    # 페이지 적용 전 전체 건수.
    total_count = db.session.scalar(
        select(func.count(Event.id)).where(*conditions)
    )
    if query["sort"] == "popular":
        # 일별 집계가 아닌 events.view_count(누적) 기준이다.
        order_by = (Event.view_count.desc(), Event.id.desc())
    elif query["sort"] == "dateAsc":
        order_by = (Event.start_date.asc(), Event.id.asc())
    else:
        order_by = (Event.created_at.desc(), Event.id.desc())

    page = query["page"]
    size = query["size"]
    statement = (
        select(Event)
        .options(joinedload(Event.category), joinedload(Event.sido))
        .where(*conditions)
        .order_by(*order_by)
        .offset((page - 1) * size)
        .limit(size)
    )
    events = db.session.scalars(statement).all()
    return {
        "total_count": total_count,
        "page": page,
        "size": size,
        "events": events,
    }

def get_event(event_id: int, today: date | None = None, request_method: str = "GET") -> Event:
    """행사 한 건을 조회하고, GET이면 조회수를 1 올린다.

    Args:
        event_id: 행사 ID.
        today: 조회수를 기록할 날짜. 생략하면 KST 오늘이다.
        request_method: HEAD 요청은 조회수에 포함하지 않는다.

    Raises:
        BusinessException: 행사가 없으면 EVENT_NOT_FOUND.
    """
    # 날짜는 잠금 대기 전에 정해 자정을 넘겨 대기해도 요청 시점의 날짜로 기록한다.
    record_view = request_method == "GET"
    view_date = today or datetime.now(KST).date()
    # 누적·일별 집계를 별도 Session의 한 트랜잭션으로 묶는다. db.session에 남은
    # 다른 변경이 함께 커밋되지 않고, 예외가 나면 둘 다 롤백된다.
    with Session(db.engine, expire_on_commit=False) as session, session.begin():
        statement = (
            select(Event)
            .options(selectinload(Event.category), selectinload(Event.sido))
            # 종료일로 막지 않는다. 지난 행사도 ID로 상세와 리뷰를 볼 수 있다.
            .where(Event.id == event_id)
        )
        if record_view:
            # 행사 행을 잠가 같은 행사의 일별 행 생성·증가를 직렬화한다. 관계를
            # selectinload(별도 SELECT)로 읽어 카테고리·지역 행은 잠그지 않는다.
            statement = statement.with_for_update()
        event = session.scalar(statement)
        if event is None:
            raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

        if record_view:
            daily_view = session.get(EventDailyView, (event.id, view_date))
            if daily_view is None:
                session.add(EventDailyView(
                    event_id=event.id,
                    view_date=view_date,
                    view_count=1,
                ))
            else:
                daily_view.view_count += 1
            # 조회수는 내용 수정이 아니므로 updated_at이 자동 갱신되지 않게 자기 값을 지정한다.
            session.execute(
                update(Event)
                .where(Event.id == event.id)
                .values(
                    view_count=Event.view_count + 1,
                    updated_at=Event.updated_at,
                )
            )
        # expire_on_commit=False와 관계 선로딩 덕분에 세션 종료 후에도 직렬화할 수 있다.
        return event
