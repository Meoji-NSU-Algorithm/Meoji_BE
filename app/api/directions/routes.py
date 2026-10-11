
from flask import Blueprint, jsonify, request

from app.common_response import CommonResponse
from app.schemas.directions import (DirectionsQuerySchema, DirectionsResponseSchema,)
from app.schemas.events import EventPathSchema
from app.services.directions_service import DirectionsService

directions_bp = Blueprint("directions", __name__, url_prefix="/directions",)


@directions_bp.get("/<int:event_id>")
def get_directions(event_id):
    # URL의 행사 ID를 검증한다.
    params = EventPathSchema().load({"event_id": event_id})

    # 쿼리 파라미터를 검증하고 Python에서 사용할 형태로 변환한다.
    query = DirectionsQuerySchema().load(request.args)

    # 서비스에서 행사 조회 및 길찾기를 처리한다.
    data = DirectionsService.get_directions(params["event_id"], query,)

    # 프로젝트의 공통 응답 형식으로 반환한다.
    return jsonify(CommonResponse.success(DirectionsResponseSchema().dump(data))), 200
