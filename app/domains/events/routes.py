"""행사 조회 API 라우트(`/api/events`).

요청 검증은 schemas, 조회 로직은 service에 위임하고 여기서는 공통 응답만 만든다.
"""

from flask import Blueprint, jsonify, request

from app.core.response import CommonResponse
from app.domains.events.schemas import (
    CategoryOptionSchema,
    EmptyQuerySchema,
    EventDetailResponseSchema,
    EventPathSchema,
    EventListQuerySchema,
    EventListResponseSchema,
    MonthlyTopQuerySchema,
    MonthlyTopResponseSchema,
    SidoOptionSchema,
)
from app.domains.events import service as event_service
from app.domains.reviews import service as review_service


# 부모 Blueprint(api_bp)가 /api를 붙인다.
events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.get("/categories")
def list_categories():
    """카테고리 선택지 목록을 반환한다.

    GET /api/events/categories. 쿼리 파라미터는 받지 않는다. 성공 시 200.
    """
    EmptyQuerySchema().load(request.args)
    categories = event_service.list_categories()
    data = CategoryOptionSchema(many=True).dump(categories)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/sidos")
def list_sidos():
    """시도 선택지 목록을 반환한다.

    GET /api/events/sidos. 쿼리 파라미터는 받지 않는다. 성공 시 200.
    """
    EmptyQuerySchema().load(request.args)
    sidos = event_service.list_sidos()
    data = SidoOptionSchema(many=True).dump(sidos)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("")
def list_events():
    """종료되지 않은 행사 목록을 필터·검색·정렬·페이지로 조회한다.

    GET /api/events. 쿼리: q, title, venue, tag, category_id, sido_code, is_free,
    start_date, end_date, sort, page, size. 결과가 없어도 200과 빈 목록을 반환한다.

    Raises:
        COMMON_INVALID_INPUT: 쿼리 검증 실패(400).
    """
    query = EventListQuerySchema().load(request.args)
    result = event_service.list_events(query)
    data = EventListResponseSchema().dump(result)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/monthly-top")
def monthly_top_events():
    """월간 조회수 상위 행사를 반환한다.

    GET /api/events/monthly-top. 쿼리: month(YYYY-MM, 생략 시 이번 달), size.
    조회 기록이 없어도 200과 빈 목록을 반환한다.

    Raises:
        COMMON_INVALID_INPUT: 쿼리 검증 실패(400).
    """
    query = MonthlyTopQuerySchema().load(request.args)
    result = event_service.monthly_top(query)
    data = MonthlyTopResponseSchema().dump(result)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/<int:event_id>")
def get_event(event_id):
    """행사 상세와 리뷰 목록·평점 요약을 한 번에 반환하고 조회수를 기록한다.

    GET /api/events/<event_id>. 쿼리 파라미터는 받지 않는다. 성공 시 200.

    Raises:
        COMMON_INVALID_INPUT: event_id 또는 쿼리 검증 실패(400).
        EVENT_NOT_FOUND: 행사가 없음(404).
    """
    EmptyQuerySchema().load(request.args)
    params = EventPathSchema().load({"event_id": event_id})
    event = event_service.get_event(params["event_id"], request_method=request.method)
    # 행사 조회가 성공한 뒤에만 리뷰를 읽는다. 리뷰 API와 같은 서비스 함수를 써서
    # 정렬과 평점 계산을 일치시킨다.
    reviews = review_service.get_reviews_by_event(event.id)
    rating = review_service.get_rating_info(event.id)
    data = EventDetailResponseSchema().dump({
        "event": event,
        "reviews": reviews,
        "review_count": rating["review_count"],
        "average_rating": rating["average_rating"],
    })
    return jsonify(CommonResponse.success(data)), 200
