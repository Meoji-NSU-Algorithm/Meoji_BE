
"""ODsay 도보 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

import math

import requests
from flask import current_app
from datetime import timedelta

from app.core.errors import BusinessException, ErrorCode


def build_walk_steps(route_data):
    """도보 경로의 안내 정보와 연결된 구간을 이동 단계로 변환한다."""

    guides = route_data.get("guides", [])
    routes = route_data.get("routes", [])

    steps = []

    for index, guide in enumerate(guides):
        guidance = guide.get("guidance")
        route_index = guide.get("routeIndex")

        if not guidance:
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
            next_route_index = next_guide.get("routeIndex")

            if (
                isinstance(next_route_index, int)
                and not isinstance(next_route_index, bool)
                and route_index < next_route_index <= len(routes)
            ):
                next_index = next_route_index
                break

        section_routes = routes[route_index:next_index]

        distance = sum(
            route["distance"]
            for route in section_routes
            if isinstance(route.get("distance"), (int, float))
            and not isinstance(route.get("distance"), bool)
        )

        duration = sum(
            route["duration"]
            for route in section_routes
            if isinstance(route.get("duration"), (int, float))
            and not isinstance(route.get("duration"), bool)
        )

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

    api_key = current_app.config.get("ODSAY_API_KEY")

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

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

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        result = response.json()

    except requests.Timeout:
        raise BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT)

    except (requests.RequestException, ValueError):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    if not isinstance(result, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    if result.get("error"):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    result_data = result.get("result")
    paths = result_data.get("path") if isinstance(result_data, dict) else None

    if not isinstance(paths, list) or not paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    path = paths[0]

    if not path.get("hasPathResult"):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    route_data = path.get("recommend")

    if not isinstance(route_data, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    summary = route_data.get("summary")

    if not isinstance(summary, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    distance = summary.get("distance")
    duration = summary.get("duration")

    if (
        not isinstance(distance, (int, float))
        or isinstance(distance, bool)
        or not math.isfinite(distance)
        or distance < 0
        or not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration < 0
    ):
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
