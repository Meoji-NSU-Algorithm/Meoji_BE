
"""카카오 자동차 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import timedelta

from flask import current_app

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import client
from app.domains.directions.core.check_function import number_or_none


def handle_kakao_http_error(error):
    """카카오 API HTTP 오류 코드를 확인한다."""

    error_response = error.response

    try:
        error_data = (
            error_response.json()
            if error_response is not None
            else {}
        )
    except ValueError:
        error_data = {}

    error_code = (
        error_data.get("code")
        if isinstance(error_data, dict)
        else None
    )

    if error_code == -2:
        raise BusinessException(
            ErrorCode.COMMON_INVALID_INPUT
        ) from None


def build_car_steps(route):
    """카카오 응답에서 자동차 이동 단계를 추출한다."""
    if not isinstance(route, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    sections = route.get("sections", [])

    if not isinstance(sections, list):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    steps = []

    for section in sections:
        # section이 딕셔너리가 아니면 건너뛴다.
        if not isinstance(section, dict):
            continue

        guides = section.get("guides", [])

        # guides가 리스트가 아니면 해당 구간을 건너뛴다.
        if not isinstance(guides, list):
            continue

        for guide in guides:
            # guide가 딕셔너리가 아니면 건너뛴다.
            if not isinstance(guide, dict):
                continue

            guidance = guide.get("guidance")

            if not guidance:
                continue

            distance = number_or_none(guide.get("distance"))
            duration = number_or_none(guide.get("duration"))

            distance = round(distance) if distance is not None else None

            duration_minutes = (round(duration / 60) if duration is not None else None)

            steps.append({
                "step_number": len(steps) + 1,
                "type": "DRIVE",
                "instruction": guidance,
                "duration_minutes": duration_minutes,
                "distance_meters": distance,
                "detail": None,
            })

    return steps


def get_car_directions(event, origin_lat, origin_lng, departure_time):
    """카카오 자동차 길찾기 API를 호출하고 결과를 반환한다."""
    api_key = current_app.config.get("KAKAO_CLIENT_ID")

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

    url_params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{float(event.longitude)},{float(event.latitude)}",
    }

    headers = {
        "Authorization": f"KakaoAK {api_key}",
    }

    result = client.get_json(
        client.KAKAO_DIRECTIONS_URL,
        params=url_params,
        headers=headers,
        provider="카카오 자동차",
        on_http_error=handle_kakao_http_error,
    )

    routes = result.get("routes") if isinstance(result, dict) else None

    if not isinstance(routes, list) or not routes:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    route = routes[0]

    if not isinstance(route, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    result_code = route.get("result_code")

    if result_code == 104:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    if result_code != 0:
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    summary = route.get("summary")

    if not isinstance(summary, dict):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    duration = number_or_none(summary.get("duration"))
    distance = number_or_none(summary.get("distance"))

    if duration is None or distance is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = departure_time + timedelta(seconds=duration)

    return {
        "event_id": event.id,
        "mode": "car",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": round(duration / 60),
        "distance_meters": distance,
        "arrival_time": arrival_time.isoformat(),
        "steps": build_car_steps(route),
    }
