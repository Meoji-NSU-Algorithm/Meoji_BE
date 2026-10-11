# 행사 HTTP 엔드포인트. 요청 검증은 스키마, 검색과 DB 조회는 서비스가 담당한다.
# 이 파일은 요청값 전달과 공통 JSON 응답 생성만 수행한다.

from flask import Blueprint, jsonify, request

from app.common_response import CommonResponse
from app.schemas.events import (
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
from app.services.event_service import EventService
# 행사 상세 응답에 같은 행사의 리뷰 목록과 평균 평점·리뷰 수를 포함하기 위해 사용한다.
from app.services.review_service import get_rating_info, get_reviews_by_event




# 부모 Blueprint가 /api를 붙이므로 여기서는 행사 경로 /event만 지정한다.
events_bp = Blueprint("events", __name__, url_prefix="/event")


@events_bp.get("/categories")
def list_categories():
    # 입력값 없는 선택지 조회. 잘못 붙인 쿼리는 스키마에서 거부한다.
    EmptyQuerySchema().load(request.args)
    categories = EventService.list_categories()
    data = CategoryOptionSchema(many=True).dump(categories)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/sidos")
def list_sidos():
    # 받은 code는 프론트에서 선택한 뒤 행사 목록 요청의 sido_code로 전달한다.
    EmptyQuerySchema().load(request.args)
    sidos = EventService.list_sidos()
    data = SidoOptionSchema(many=True).dump(sidos)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("")
def list_events():
    # 한국 시간 기준 이미 끝난 행사는 제외한다. q 통합 검색과 title·venue·tag
    # 세부 검색을 포함한 나머지 조건은 스키마에서 검증하고 서비스에서 적용한다.
    # 모두 같은 GET /api/event 경로를 사용하며, 응답의 행사 카드 형식도 동일하다.
    query = EventListQuerySchema().load(request.args)
    result = EventService.list_events(query)
    data = EventListResponseSchema().dump(result)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/monthly-top")
def monthly_top_events():
    # 조회할 월과 카드 개수를 검증한다. 월 경계와 순위 계산은 서비스에서 맡는다.
    query = MonthlyTopQuerySchema().load(request.args)
    result = EventService.monthly_top(query)
    data = MonthlyTopResponseSchema().dump(result)
    return jsonify(CommonResponse.success(data)), 200


@events_bp.get("/<int:event_id>")
def get_event(event_id):
    # 경로의 정수 ID로 행사를 조회하고 서비스에서 조회수를 기록한다.
    # 행사 상세 화면은 행사 정보와 리뷰를 함께 보여준다. 같은 행사 ID의 리뷰와
    # 평점 요약까지 이 요청에서 조회해 프론트가 리뷰 API를 별도로 호출하지 않게 한다.
    EmptyQuerySchema().load(request.args)
    params = EventPathSchema().load({"event_id": event_id})
    event = EventService.get_event(params["event_id"], request_method=request.method)
    # 행사 조회가 먼저 성공해야 없는 행사에 대한 리뷰 조회를 하지 않는다.
    # 기존 리뷰 API와 같은 서비스 함수를 재사용해 리뷰 정렬과 평점 계산을 맞춘다.
    reviews = get_reviews_by_event(event.id)
    rating = get_rating_info(event.id)
    # 리뷰가 없으면 reviews는 빈 목록이고, 평점 서비스는 개수와 평균을 0으로 준다.
    # 응답 스키마가 행사 필드를 최상위에 두고 리뷰 관련 필드를 추가한다.
    data = EventDetailResponseSchema().dump({
        "event": event,
        "reviews": reviews,
        "review_count": rating["review_count"],
        "average_rating": rating["average_rating"],
    })
    return jsonify(CommonResponse.success(data)), 200
