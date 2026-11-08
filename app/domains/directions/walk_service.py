
"""ODsay 도보 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import timedelta

from flask import current_app

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import client
from app.domains.directions.core.check_function import number_or_none


def build_walk_steps(route_data):
    """도보 경로의 안내 정보와 연결된 구간을 이동 단계로 변환한다."""
    guides = route_data.get("guides", [])
    routes = route_data.get("routes", [])

    # 안내 정보와 경로 정보가 리스트인지 확인한다.
    if not isinstance(guides, list) or not isinstance(routes, list):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    # 경로 구간의 자료형만 확인한다.
    # 잘못된 구간은 아래 합산 과정에서 제외한다.
    # 각 구간의 원래 인덱스를 유지하면서 정상 데이터만 저장한다.
    valid_routes = []

    for route in routes:
        if not isinstance(route, dict):
            valid_routes.append(None)
            continue

        distance = number_or_none(route.get("distance"))
        duration = number_or_none(route.get("duration"))

        if distance is None or duration is None:
            valid_routes.append(None)
            continue

        valid_routes.append({
            "distance": distance,
            "duration": duration,
        })


    steps = []

    for index, guide in enumerate(guides):
        # 안내 항목이 딕셔너리가 아니면 건너뛴다.
        if not isinstance(guide, dict):
            continue

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

        # 다음 안내 지점 직전까지의 경로 구간을 확인한다.
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

        # 해당 안내 구간에 포함되는 정상 경로만 합산한다.
        section_routes = valid_routes[route_index:next_index]

        distance = sum(route["distance"] for route in section_routes if route is not None)
        duration = sum(route["duration"] for route in section_routes if route is not None)

        steps.append({
            "step_number": len(steps) + 1,
            "type": "WALK",
            "instruction": guidance,
            "duration_minutes": (round(duration / 60) if duration is not None else None),
            "distance_meters": (round(distance) if distance is not None else None),
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

    params = {
        "apiKey": api_key,
        "lang": 0,
        "opt": "reco",
        "loc": (
            f"{origin_lng},{origin_lat},"
            f"{float(event.longitude)},{float(event.latitude)}"
        ),
        "output": "json",
    }

    # 공통 클라이언트를 통해 ODsay 도보 API를 호출한다.
    result = client.get_json(
        client.ODSAY_WALK_URL,
        params=params,
        provider="ODsay 도보",
    )

    if not isinstance(result, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    # ODsay 오류 응답을 공통 클라이언트에서 처리한다.
    client.raise_odsay_error(result, "ODsay 도보")

    result_data = result.get("result")
    paths = result_data.get("path") if isinstance(result_data, dict) else None

    if not isinstance(paths, list) or not paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    path = paths[0]

    if not isinstance(path, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    if not path.get("hasPathResult"):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    route_data = path.get("recommend")

    if not isinstance(route_data, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    summary = route_data.get("summary")

    if not isinstance(summary, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    distance = number_or_none(summary.get("distance"))
    duration = number_or_none(summary.get("duration"))

    if distance is None or duration is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = departure_time + timedelta(seconds=duration)

    return {
        "event_id": event.id,
        "mode": "walk",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": round(duration / 60),
        "distance_meters": round(distance),
        "arrival_time": arrival_time.isoformat(),
        "steps": build_walk_steps(route_data),
    }
