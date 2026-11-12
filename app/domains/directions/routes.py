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