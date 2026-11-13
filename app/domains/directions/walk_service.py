"""ODsay 도보 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import timedelta

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions.client import get_api_key, request_json
from app.domains.directions.core.utils import valid_number_or_none


def build_walk_steps(route_data):
    """도보 경로의 안내 정보와 연결된 구간을 이동 단계로 변환한다."""

    guides = route_data.get("guides", [])
    routes = route_data.get("routes", [])

    if not isinstance(guides, list) or not isinstance(routes, list):
        return []

    steps = []

    for index, guide in enumerate(guides):
        if not isinstance(guide, dict):
            continue

        guidance = guide.get("guidance")
        route_index = guide.get("routeIndex")

        if not isinstance(guidance, str) or not guidance:
            continue

        if (
            not isinstance(route_index, int)
            or isinstance(route_index, bool)
            or not 0 <= route_index < len(routes)
        ):
            continue

        # 다음 안내 지점 직전까지의 경로 구간을 합산한다.
        next_index = len(routes)

        for next_guide in guides[index + 1:]:
            if not isinstance(next_guide, dict):
                continue

            next_route_index = next_guide.get("routeIndex")

            if (
                isinstance(next_route_index, int)
                and not isinstance(next_route_index, bool)
                and route_index < next_route_index <= len(routes)
            ):
                next_index = next_route_index
                break

        section_routes = routes[route_index:next_index]

        distances = []
        durations = []

        for route in section_routes:
            if not isinstance(route, dict):
                continue

            distance = valid_number_or_none(route.get("distance"))
            duration = valid_number_or_none(route.get("duration"))

            if distance is not None:
                distances.append(distance)

            if duration is not None:
                durations.append(duration)

        distance = sum(distances)
        duration = sum(durations)

        steps.append({
            "step_number": len(steps) + 1,
            "type": "WALK",
            "instruction": guidance,
            "duration_minutes": round(duration / 60, 1),
            "distance_meters": distance,
            "detail": {
                "point": guide.get("point"),
                "angle": guide.get("angle"),
                "turn": guide.get("turn"),
                "facility": guide.get("facility"),
            },
        })

    return steps


def get_walk_directions(event, origin_lat, origin_lng, departure_time):
    """ODsay 도보 길찾기 API를 호출하고 추천 경로를 반환한다."""

    api_key = get_api_key("ODSAY_API_KEY")

    url = "https://api.odsay.com/v1/api/searchWalkPathV2"

    params = {
        "apiKey": api_key,
        "opt": "reco",
        "loc": (
            f"{origin_lng},{origin_lat},"
            f"{float(event.longitude)},{float(event.latitude)}"
        ),
        "output": "json",
    }

    result = request_json(url, params)

    if result.get("error"):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    result_data = result.get("result")
    paths = result_data.get("path") if isinstance(result_data, dict) else None

    if not isinstance(paths, list) or not paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    path = paths[0]

    if not isinstance(path, dict) or not path.get("hasPathResult"):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    route_data = path.get("recommend")

    if not isinstance(route_data, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    summary = route_data.get("summary")

    if not isinstance(summary, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    distance = valid_number_or_none(summary.get("distance"))
    duration = valid_number_or_none(summary.get("duration"))

    if distance is None or duration is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = departure_time + timedelta(seconds=duration)

    return {
        "event_id": event.id,
        "mode": "walk",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": round(duration / 60),
        "distance_meters": distance,
        "arrival_time": arrival_time.isoformat(),
        "steps": build_walk_steps(route_data),
    }