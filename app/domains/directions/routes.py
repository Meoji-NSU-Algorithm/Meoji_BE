
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
    """행사 ID와 출발지 좌표를 받아 이동 경로를 조회한다. (JWT 필요, 없으면 401)"""

    params = EventPathSchema().load({"event_id": event_id})
    query = DirectionsQuerySchema().load(request.args)

    data = directions_service.get_directions(params["event_id"], query)

    result = DirectionsResponseSchema().dump(data)

    return jsonify(CommonResponse.success(result)), 200
