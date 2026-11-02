
"""ODsay 대중교통 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

import math
from datetime import datetime, timedelta

import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST


def build_transit_steps(path):
    """ODsay 응답에서 도보·버스·지하철 이동 단계를 추출한다."""

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

    if not isinstance(result, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    if result.get("error"):
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
