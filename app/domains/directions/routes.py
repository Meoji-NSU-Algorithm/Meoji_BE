"""길찾기 API 요청을 받고 결과를 공통 응답 형식으로 반환한다."""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.core.response import CommonResponse
from app.domains.directions import service as directions_service
from app.domains.directions.schemas import (
    DirectionsQuerySchema,
    DirectionsResponseSchema,
)
from app.domains.events.schemas import EventPathSchema

directions_bp = Blueprint("directions", __name__, url_prefix="/directions")


@directions_bp.get("/<int:event_id>")
@jwt_required()
def get_directions(event_id):
    """행사까지의 이동 경로를 조회한다.

    GET /api/directions/<event_id>. JWT 필요. 쿼리: originLat, originLng, mode.

    Raises:
        COMMON_INVALID_INPUT: 쿼리 검증 실패(400).
        EVENT_NOT_FOUND / ROUTE_NOT_FOUND: 행사 또는 경로가 없음(404).
        DIRECTIONS_API_ERROR / DIRECTIONS_API_TIMEOUT / DIRECTIONS_API_KEY_MISSING: 외부 서비스 문제(502/504/500).
    """

    # 행사 ID 검증
    params = EventPathSchema().load({"event_id": event_id})

    # 쿼리 파라미터 검증
    query = DirectionsQuerySchema().load(request.args)

    # 길찾기 서비스 호출
    data = directions_service.get_directions(params["event_id"], query)

    result = DirectionsResponseSchema().dump(data)

    return jsonify(CommonResponse.success(result)), 200
