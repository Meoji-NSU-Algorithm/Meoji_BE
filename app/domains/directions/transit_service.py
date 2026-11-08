
"""ODsay 대중교통 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import datetime, timedelta

from flask import current_app

from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST
from app.domains.directions import client
from app.domains.directions.core.check_function import number_or_none


def build_transit_steps(path):
    """ODsay 응답에서 도보·버스·지하철 이동 단계를 추출한다."""
    if not isinstance(path, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    rps = path.get("rps", [])

    # 이동 단계 목록이 리스트인지 확인한다.
    if not isinstance(rps, list):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    steps = []

    for part in rps:
        # 각 이동 단계가 딕셔너리가 아니면 건너뛴다.
        if not isinstance(part, dict):
            continue

        traffic_type = part.get("trafficType")

        if traffic_type == 1:
            step_type = "SUBWAY"
        elif traffic_type == 2:
            step_type = "BUS"
        elif traffic_type == 3:
            step_type = "WALK"
        else:
            step_type = "OTHER"

        distance = number_or_none(part.get("distance"))
        duration = number_or_none(part.get("duration"))

        # lane이 리스트가 아니면 빈 리스트로 처리한다.
        lanes = part.get("lane") or []

        if not isinstance(lanes, list):
            lanes = []

        # 상세 정보는 객체 또는 None으로 반환한다.
        detail = {}

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

            # 출발역 출구 정보
            if part.get("startExitNo") is not None:
                detail["startExitNo"] = str(part["startExitNo"])

            # 도착역 출구 정보
            if part.get("endExitNo") is not None:
                detail["endExitNo"] = str(part["endExitNo"])

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

            # passStopList가 딕셔너리인지 확인한다.
            pass_stop_list = part.get("passStopList")

            stations = (
                pass_stop_list.get("stations", [])
                if isinstance(pass_stop_list, dict)
                else []
            )

            # 경유 정류장 개수를 상세 정보로 저장한다.
            if isinstance(stations, list) and stations:
                detail["stopCount"] = len(stations)

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
            "duration_minutes": round(duration) if duration is not None else None,
            "distance_meters": round(distance) if distance is not None else None,
            "detail": detail if detail else None,
        })

    return steps


def get_transit_directions(event, origin_lat, origin_lng, departure_time):
    """ODsay 대중교통 길찾기 API를 호출하고 결과를 반환한다."""
    api_key = current_app.config.get("ODSAY_API_KEY")

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

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

    # 공통 클라이언트를 통해 ODsay 대중교통 API를 호출한다.
    result = client.get_json(
        client.ODSAY_TRANSIT_URL,
        params=params,
        provider="ODsay 대중교통",
    )

    if not isinstance(result, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    # ODsay 오류 응답이 있는지 확인한다.
    error = result.get("error")

    if error:
        # 오류 응답이 리스트 또는 딕셔너리인지 확인한다.
        first = error[0] if isinstance(error, list) and error else error

        # 오류 코드 추출
        code = (
            str(first.get("code", ""))
            if isinstance(first, dict)
            else ""
        )

        # 오류 코드 로그 출력
        current_app.logger.warning(
            "ODsay 대중교통 오류 응답: code=%s", code
        )

        # 검색 데이터가 없으면 경로 없음으로 처리한다.
        if code == "400":
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND) from None

        # 필수 파라미터 누락 및 형식 오류
        if code == "401":
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT) from None

        # 나머지 오류는 외부 API 오류로 처리한다.
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR) from None

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

    duration = number_or_none(path.get("totalTime"))
    distance = number_or_none(path.get("totalDistance"))

    if duration is None or distance is None:
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
        "duration_minutes": round(duration),
        "distance_meters": round(distance),
        "arrival_time": arrival_time,
        "steps": build_transit_steps(path),
    }
