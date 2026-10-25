# 저장된 행사를 화면에 제공하는 조회 서비스. 외부 TourAPI 수집과 분리한다.
# 라우트가 SQL 조건과 페이지 계산을 몰라도 되도록 목록·상세 조회를 맡는다.

from calendar import monthrange
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, joinedload, selectinload

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.events.models import Category, Event, EventDailyView, Sido, Tag


# 화면의 월간 순위와 상세 조회 날짜는 한국 달력 날짜로 계산한다.
KST = timezone(timedelta(hours=9))


def _contains_keyword(value):
    # q와 세부 검색어를 모두 SQL의 '문자열 포함' 검색 패턴으로 바꾼다.
    # 앞뒤 공백만 제거하며, 공백만 보냈으면 검색 조건을 만들지 않는다.
    text = (value or "").strip()
    if not text:
        return None
    # LIKE에서 %는 여러 글자, _는 한 글자를 뜻한다. 사용자가 입력한 기호는
    # 검색 명령이 아닌 실제 글자로 찾도록 \\를 앞에 붙인다. \\ 자체도 이스케이프한다.
    # 앞뒤의 %만 부분 일치 검색을 위해 코드에서 붙인다.
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class EventService:
    @staticmethod
    def list_categories():
        # 행사 유무와 관계없이 기준 테이블의 전체 선택지를 표시 순서대로 반환한다.
        # 같은 sort_order는 ID로 정렬해 응답 순서를 일정하게 유지한다.
        statement = select(Category).order_by(Category.sort_order, Category.id)
        return db.session.scalars(statement).all()

    @staticmethod
    def list_sidos():
        # 지역명이나 순서를 코드에 고정하지 않고 마이그레이션으로 넣은 기준값을 읽는다.
        # code는 숫자 수량이 아닌 식별 문자열이므로 응답에서도 두 자리를 유지한다.
        statement = select(Sido).order_by(Sido.sort_order, Sido.code)
        return db.session.scalars(statement).all()

    @staticmethod
    def monthly_top(query, today=None):
        # 선택한 달이 없으면 한국 시간의 현재 달을 사용한다. 조회 기록이
        # 부족할 때 채울 추천 행사도 같은 날짜의 진행 여부로 판단한다.
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

        # 카테고리와 관계없이 해당 월에 조회수 기록이 있는 현재 행사를
        # 순위에 넣는다. 월간 합계가 같으면 행사 ID 내림차순으로 고정한다.
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
            # 신규 서비스처럼 일별 조회 기록이 없거나 적어도 빈 화면을 내지 않는다.
            # 이미 순위에 든 ID를 제외하고 종료일이 가까운 현재 행사부터 채운다.
            ranked_ids = [event.id for event, _ in rows]
            recommendations = db.session.scalars(
                select(Event)
                .options(joinedload(Event.category), joinedload(Event.sido))
                .where(Event.end_date >= current_date, Event.id.not_in(ranked_ids))
                .order_by(Event.end_date.asc(), Event.start_date.asc(), Event.id.asc())
                .limit(query["size"] - len(rows))
            ).all()
            rows.extend((event, 0) for event in recommendations)
        # DB에 보여줄 현재 행사가 전혀 없을 때만 행사 없음 오류를 반환한다.
        if not rows:
            raise BusinessException(ErrorCode.EVENT_NOT_FOUND)
        return {
            "month": f"{month.year:04d}-{month.month:02d}",
            "events": [
                {"event": event, "monthly_views": views}
                for event, views in rows
            ],
        }

    @staticmethod
    def list_events(query):
        # 요청에 있는 필터만 SQL 조건에 추가한다. 태그 검색은 EXISTS를 사용해
        # 태그가 여러 개 맞아도 한 행사가 중복되거나 totalCount가 부풀지 않게 한다.
        # 지난 행사는 리뷰와 함께 DB에 보관하되 목록 화면에서는 제외한다.
        # 오늘 종료하는 행사는 오늘까지 표시한다. 다른 검색 조건보다 먼저
        # 이 조건을 넣어 모든 카테고리·지역·검색 목록에 동일하게 적용한다.
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

        # q는 기존 통합 검색이다. ilike()로 대소문자를 구분하지 않고,
        # 제목·장소·연결된 태그 중 한 곳에만 검색어가 있어도 결과에 넣는다.
        keyword = _contains_keyword(query["q"])
        if keyword:
            conditions.append(
                or_(
                    Event.title.ilike(keyword, escape="\\"),
                    Event.venue_name.ilike(keyword, escape="\\"),
                    Event.tags.any(Tag.name.ilike(keyword, escape="\\")),
                )
            )

        # 세부 검색은 각자 지정한 필드만 검사한다. 조건 목록은 아래 SQL의
        # where(*conditions)에서 AND로 묶여 q·카테고리·지역 등과 함께 적용된다.
        title_keyword = _contains_keyword(query["title"])
        if title_keyword:
            # 제목에만 포함된 문자열을 찾는다. 장소·태그 일치는 여기서 제외한다.
            conditions.append(Event.title.ilike(title_keyword, escape="\\"))
        venue_keyword = _contains_keyword(query["venue"])
        if venue_keyword:
            # 장소명(events.venue_name)에만 포함된 문자열을 찾는다.
            conditions.append(Event.venue_name.ilike(venue_keyword, escape="\\"))
        tag_keyword = _contains_keyword(query["tag"])
        if tag_keyword:
            # 소개글에서 추출되어 event_tags로 연결된 태그 이름만 검사한다.
            # 태그 연결 테이블을 직접 JOIN하면 한 행사에 여러 태그가 맞을 때
            # 목록과 totalCount가 중복된다. EXISTS로 연결 여부만 확인한다.
            conditions.append(Event.tags.any(Tag.name.ilike(tag_keyword, escape="\\")))

        # 페이지네이션 전 전체 건수를 세어 프론트가 페이지 수를 계산하게 한다.
        total_count = db.session.scalar(
            select(func.count(Event.id)).where(*conditions)
        )
        if query["sort"] == "popular":
            # 현재는 events의 누적 조회수를 기준으로 정렬한다.
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
        # 검색 결과가 없거나 요청 페이지가 범위를 넘으면 빈 목록 대신 404를 반환한다.
        if not events:
            raise BusinessException(ErrorCode.EVENT_NOT_FOUND)
        return {
            "total_count": total_count,
            "page": page,
            "size": size,
            "events": events,
        }

    @staticmethod
    def get_event(event_id, today=None, request_method="GET"):
        # HEAD는 존재 여부와 헤더만 확인하는 요청이므로 조회수에 포함하지 않는다.
        # 날짜는 잠금 대기 전에 정해 자정에 대기 시간이 길어져도 요청 날짜로 기록한다.
        record_view = request_method == "GET"
        view_date = today or datetime.now(KST).date()
        # 독립 세션의 트랜잭션으로 집계 두 개를 묶는다. 예외가 나면 자동 롤백되며,
        # 다른 서비스가 db.session에 남긴 변경을 여기서 함께 커밋하지 않는다.
        with Session(db.engine, expire_on_commit=False) as session, session.begin():
            statement = (
                select(Event)
                .options(selectinload(Event.category), selectinload(Event.sido))
                # 지난 행사는 목록에서만 제외한다. 저장된 행사 ID로 직접 들어오면
                # 상세 정보와 연결된 리뷰를 계속 볼 수 있도록 종료일로 막지 않는다.
                .where(Event.id == event_id)
            )
            if record_view:
                # MySQL에서는 행사 행 잠금으로 같은 행사 집계를 순차 처리한다.
                # 관계는 별도 SELECT로 읽어 카테고리·지역 행까지 잠그지 않는다.
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
                # 조회수는 행사 내용 수정이 아니므로 updated_at의 자동 갱신을 막는다.
                # 누적값은 DB에서 1을 더하고 일별 행과 같은 트랜잭션으로 확정한다.
                session.execute(
                    update(Event)
                    .where(Event.id == event.id)
                    .values(
                        view_count=Event.view_count + 1,
                        updated_at=Event.updated_at,
                    )
                )
            # 응답에 필요한 관계를 미리 읽었으므로 세션 종료 후에도 직렬화할 수 있다.
            return event
