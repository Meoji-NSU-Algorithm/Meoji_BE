"""카카오 자동차 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import timedelta

from app.core.errors import BusinessException, ErrorCode

from app.domains.directions.client import get_api_key, request_json
from app.domains.directions.core.utils import (valid_number_or_none)


def build_car_steps(route):
    """카카오 응답에서 자동차 이동 단계를 추출한다."""

    sections = route.get("sections", [])

    if not isinstance(sections, list):
        return []

    steps = []

    for section in sections:
        if not isinstance(section, dict):
            continue

        guides = section.get("guides", [])

        if not isinstance(guides, list):
            continue

        for guide in guides:
            if not isinstance(guide, dict):
                continue

            guidance = guide.get("guidance")

            if not isinstance(guidance, str) or not guidance:
                continue

            distance = valid_number_or_none(guide.get("distance"))
            duration = valid_number_or_none(guide.get("duration"))

            steps.append({
                "step_number": len(steps) + 1,
                "type": "DRIVE",
                "instruction": guidance,
                "duration_minutes": (
                    round(duration / 60) if duration is not None else None
                ),
                "distance_meters": (
                    round(distance) if distance is not None else None
                ),
                "detail": None,
            })

    return steps


def build_car_path(route):
    """카카오 응답에서 지도에 표시할 자동차 경로 좌표를 추출한다."""
    sections = route.get("sections", [])

    if not isinstance(sections, list):
        return []

    coordinates = []

    for section in sections:
        if not isinstance(section, dict):
            continue

        roads = section.get("roads", [])

        if not isinstance(roads, list):
            continue

        for road in roads:
            if not isinstance(road, dict):
                continue

            vertexes = road.get("vertexes", [])

            if not isinstance(vertexes, list):
                continue

            for i in range(0, len(vertexes) - 1, 2):
                lng = valid_number_or_none(vertexes[i])
                lat = valid_number_or_none(vertexes[i + 1])

                if lat is not None and lng is not None:
                    coordinates.append([lat, lng])

    return coordinates


def get_car_directions(event, origin_lat, origin_lng, departure_time):
    """카카오 자동차 길찾기 API를 호출하고 결과를 반환한다."""

    api_key = get_api_key("KAKAO_CLIENT_ID")

    url = "https://apis-navi.kakaomobility.com/v1/directions"

    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": (
            f"{float(event.longitude)},{float(event.latitude)}"
        ),
    }

    headers = {
        "Authorization": f"KakaoAK {api_key}",
    }

    result = request_json(url, params, headers)

    routes = result.get("routes")

    if not isinstance(routes, list) or not routes:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    route = routes[0]

    if not isinstance(route, dict) or route.get("result_code") != 0:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    summary = route.get("summary")

    if not isinstance(summary, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    duration = valid_number_or_none(summary.get("duration"))
    distance = valid_number_or_none(summary.get("distance"))

    if duration is None or distance is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = departure_time + timedelta(seconds=duration)

    car_path = build_car_path(route)

    if not car_path:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    return {
        "event_id": event.id,
        "mode": "car",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": round(duration / 60),
        "distance_meters": distance,
        "arrival_time": arrival_time.isoformat(),
        "path": car_path,
        "steps": build_car_steps(route),
    }