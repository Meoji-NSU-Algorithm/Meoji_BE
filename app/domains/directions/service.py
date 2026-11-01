
"""자동차 및 대중교통 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

import math
from datetime import datetime, timedelta

import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Event


def get_directions(event_id, query):
    """행사와 출발지 정보를 바탕으로 이동 경로를 조회한다."""

    event = db.session.get(Event, event_id)

    if event is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    if event.latitude is None or event.longitude is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    try:
        origin_lat = float(query["origin_lat"])
        origin_lng = float(query["origin_lng"])
    except (KeyError, TypeError, ValueError):
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

    if (
        not math.isfinite(origin_lat)
        or not math.isfinite(origin_lng)
        or not -90 <= origin_lat <= 90
        or not -180 <= origin_lng <= 180
    ):
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

    mode = query.get("mode", "car")
    departure_time = datetime.now(KST)

    if mode == "car":
        return get_car_directions(
            event, origin_lat, origin_lng, departure_time
        )

    if mode == "transit":
        return get_transit_directions(
            event, origin_lat, origin_lng, departure_time
        )

    raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)



def build_car_steps(route):
    """카카오 길찾기 응답에서 자동차 이동 단계를 추출한다."""

    steps = []

    for section in route.get("sections", []):
        for guide in section.get("guides", []):
            guidance = guide.get("guidance")

            if not guidance:
                continue

            distance = guide.get("distance")
            duration = guide.get("duration")

            steps.append({
                "step_number": len(steps) + 1,
                "type": "DRIVE",
                "instruction": guidance,
                "duration_minutes": (
                    round(duration / 60)
                    if isinstance(duration, (int, float))
                    else None
                ),
                "distance_meters": (
                    round(distance)
                    if isinstance(distance, (int, float))
                    else None
                ),
                "detail": None,
            })

    return steps



def get_car_directions(event, origin_lat, origin_lng, departure_time):
    """카카오 자동차 길찾기 API를 호출하고 결과를 반환한다."""

    api_key = current_app.config.get("KAKAO_CLIENT_ID")

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

    url = "https://apis-navi.kakaomobility.com/v1/directions"

    headers = {
        "Authorization": f"KakaoAK {api_key}",
    }

    params = {
        "origin": f"{origin_lng},{origin_lat}",
        "destination": f"{event.longitude},{event.latitude}",
        "priority": "RECOMMEND",
    }

    try:
        response = requests.get(
            url, headers=headers, params=params, timeout=10
        )
        response.raise_for_status()
        result = response.json()

    except requests.Timeout:
        raise BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT)

    except (requests.RequestException, ValueError):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    routes = result.get("routes", [])

    if not routes or routes[0].get("result_code") != 0:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    summary = routes[0].get("summary", {})
    duration = summary.get("duration")
    distance = summary.get("distance")

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
        "steps": build_car_steps(routes[0]),
    }


def build_transit_steps(path):
    """ODsay 대중교통 경로에서 도보·버스·지하철 단계를 추출한다."""

    steps = []

    for part in path.get("rps", []):
        traffic_type = part.get("trafficType")

        if traffic_type == 1:
            step_type = "SUBWAY"
        elif traffic_type == 2:
            step_type = "BUS"
        elif traffic_type == 3:
            step_type = "WALK"
        else:
            step_type = "OTHER"

        distance = part.get("distance")
        duration = part.get("duration")
        lanes = part.get("lane") or []

        details = []
        start_name = part.get("startName")
        end_name = part.get("endName")

        if step_type == "SUBWAY":
            line_names = [
                lane.get("name")
                for lane in lanes
                if isinstance(lane, dict) and lane.get("name")
            ]

            line_name = ", ".join(line_names) or "지하철"
            instruction = f"{line_name} 탑승"

            if end_name:
                instruction += f", {end_name}역 하차"

            if part.get("way"):
                instruction += f" ({part['way']} 방면)"

            if part.get("startExitNo"):
                details.append(f"출발역 {part['startExitNo']}번 출구")

            if part.get("endExitNo"):
                details.append(f"도착역 {part['endExitNo']}번 출구")

        elif step_type == "BUS":
            bus_numbers = [
                str(lane.get("busNo"))
                for lane in lanes
                if isinstance(lane, dict) and lane.get("busNo")
            ]

            bus_name = ", ".join(bus_numbers) or "버스"
            instruction = f"{bus_name}번 버스 이용"

            if start_name and end_name:
                instruction += f": {start_name} 승차 → {end_name} 하차"
            elif start_name:
                instruction += f": {start_name} 승차"
            elif end_name:
                instruction += f": {end_name} 하차"

            stations = (
                part.get("passStopList") or {}
            ).get("stations", [])

            if stations:
                details.append(f"경유 정류장 정보 {len(stations)}개")

        elif step_type == "WALK":
            instruction = "도보 이동"

            walking_guides = [
                guide.get("GUIDANCE")
                for guide in (part.get("guides") or [])
                if isinstance(guide, dict) and guide.get("GUIDANCE")
            ]

            if walking_guides:
                instruction = " → ".join(walking_guides)

        else:
            instruction = "이동"

        steps.append({
            "step_number": len(steps) + 1,
            "type": step_type,
            "instruction": instruction,
            "duration_minutes": duration,
            "distance_meters": distance,
            "detail": ", ".join(details) if details else None,
        })

    return steps


def get_transit_directions(event, origin_lat, origin_lng, departure_time):
    """ODsay 대중교통 길찾기 API를 호출하고 결과를 반환한다."""

    api_key = current_app.config.get("ODSAY_API_KEY")

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

    url = "https://api.odsay.com/v1/api/maasRP"

    params = {
        "SX": origin_lng,
        "SY": origin_lat,
        "EX": float(event.longitude),
        "EY": float(event.latitude),
        "SearchTime": departure_time.strftime("%Y%m%d%H%M"),
        "SearchMethod": 2,
        "apiKey": api_key,
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

    if not isinstance(result, dict) or result.get("error"):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    result_data = result.get("result")
    paths = result_data.get("paths") if isinstance(result_data, dict) else None

    if not isinstance(paths, list) or not paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    transit_paths = [
        path for path in paths
        if isinstance(path, dict) and path.get("pathType") == 2
    ]

    if not transit_paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    path = transit_paths[0]

    duration = path.get("totalTime")
    distance = path.get("totalDistance")

    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or not math.isfinite(duration)
        or duration < 0
        or not isinstance(distance, (int, float))
        or isinstance(distance, bool)
        or not math.isfinite(distance)
        or distance < 0
    ):
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = path.get("endDateTime")

    if arrival_time:
        try:
            arrival_time = datetime.strptime(
                arrival_time, "%Y%m%d%H%M"
            ).replace(tzinfo=KST).isoformat()
        except (TypeError, ValueError):
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)
    else:
        arrival_time = (
            departure_time + timedelta(minutes=duration)
        ).isoformat()

    return {
        "event_id": event.id,
        "mode": "transit",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": duration,
        "distance_meters": distance,
        "arrival_time": arrival_time,
        "steps": build_transit_steps(path),
    }



