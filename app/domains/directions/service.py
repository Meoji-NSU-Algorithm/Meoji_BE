
"""길찾기 요청의 공통 검증과 이동 방식 분기를 담당한다."""

import math
from datetime import datetime

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Event
from app.domains.directions import car_service, transit_service, walk_service


def get_directions(event_id, query):
    """행사와 출발지 정보를 검증하고 이동 방식에 맞는 경로를 조회한다."""

    event = db.session.get(Event, event_id)

    if event is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    if event.latitude is None or event.longitude is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    try:
        origin_lat = float(query["origin_lat"])
        origin_lng = float(query["origin_lng"])
        destination_lat = float(event.latitude)
        destination_lng = float(event.longitude)
    except (KeyError, TypeError, ValueError):
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

    if not all(map(math.isfinite, (origin_lat, origin_lng, destination_lat, destination_lng,))):
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

    if not (-90 <= origin_lat <= 90 and -180 <= origin_lng <= 180):
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

    if not (-90 <= destination_lat <= 90 and -180 <= destination_lng <= 180):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    mode = query.get("mode", "transit")
    departure_time = datetime.now(KST)

    if mode == "car":
        return car_service.get_car_directions(event, origin_lat, origin_lng, departure_time)

    if mode == "transit":
        return transit_service.get_transit_directions(event, origin_lat, origin_lng, departure_time)

    if mode == "walk":
        return walk_service.get_walk_directions(event, origin_lat, origin_lng, departure_time)

    raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

