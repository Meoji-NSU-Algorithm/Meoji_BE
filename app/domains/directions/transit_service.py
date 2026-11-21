"""ODsay 대중교통 길찾기 API 호출과 경로 데이터 가공을 담당한다."""

from datetime import datetime, timedelta

from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST

from app.domains.directions.client import get_api_key, request_json
from app.domains.directions.core.utils import (valid_number_or_none)


def build_transit_steps(path):
    """ODsay 응답에서 도보·버스·지하철 이동 단계를 추출한다."""

    parts = path.get("rps", [])

    if not isinstance(parts, list):
        return []

    steps = []

    for part in parts:
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

        distance = valid_number_or_none(part.get("distance"))
        duration = valid_number_or_none(part.get("duration"))

        lanes = part.get("lane") or []

        if not isinstance(lanes, list):
            lanes = []

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

            pass_stop_list = part.get("passStopList")
            stations = (
                pass_stop_list.get("stations", [])
                if isinstance(pass_stop_list, dict)
                else []
            )

            if isinstance(stations, list) and stations:
                details.append(f"경유 정류장 정보 {len(stations)}개")

        elif step_type == "WALK":
            instruction = "도보 이동"

            guides = part.get("guides") or []

            if not isinstance(guides, list):
                guides = []

            walking_guides = [
                guide.get("GUIDANCE")
                for guide in guides
                if (
                    isinstance(guide, dict)
                    and isinstance(guide.get("GUIDANCE"), str)
                    and guide.get("GUIDANCE")
                )
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


def build_transit_path(path):
    """ODsay 응답에서 지도에 표시할 이동 경로 좌표를 추출한다."""

    parts = path.get("rps", [])

    if not isinstance(parts, list):
        return []

    result = []

    for part in parts:
        if not isinstance(part, dict):
            continue

        traffic_type = part.get("trafficType")

        # 지하철, 버스, 도보, 열차, 고속버스, 시외버스
        if traffic_type not in (1, 2, 3, 4, 5, 6):
            continue

        coordinates = []

        # 도보는 routes 안의 xyInfos에서 좌표 추출
        if traffic_type == 3:
            routes = part.get("routes", [])

            if not isinstance(routes, list):
                continue

            for route in routes:
                if not isinstance(route, dict):
                    continue

                points = route.get("xyInfos", [])

                if not isinstance(points, list):
                    continue

                for point in points:
                    if not isinstance(point, dict):
                        continue

                    lng = valid_number_or_none(point.get("x"))
                    lat = valid_number_or_none(point.get("y"))

                    if lat is not None and lng is not None:
                        coordinates.append([lat, lng])

        # 지하철, 버스, 시외 교통은 graph에서 좌표 추출
        else:
            graph = part.get("graph")

            if isinstance(graph, str):
                for point in graph.split("|"):
                    try:
                        lng, lat = map(float, point.split())
                    except (TypeError, ValueError):
                        continue

                    lat = valid_number_or_none(lat)
                    lng = valid_number_or_none(lng)

                    if lat is not None and lng is not None:
                        coordinates.append([lat, lng])

        if coordinates:
            result.append({
                "type": (
                    "SUBWAY"
                    if traffic_type == 1
                    else "BUS"
                    if traffic_type == 2
                    else "WALK"
                    if traffic_type == 3
                    else "OTHER"
                ),
                "coordinates": coordinates,
            })

    return result



def get_transit_directions(event, origin_lat, origin_lng, departure_time):
    """ODsay 대중교통 길찾기 API를 호출하고 결과를 반환한다."""

    api_key = get_api_key("ODSAY_API_KEY")

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

    result = request_json(url, params)

    if result.get("error"):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    result_data = result.get("result")
    paths = result_data.get("paths") if isinstance(result_data, dict) else None

    if not isinstance(paths, list) or not paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    transit_paths = [
        path
        for path in paths
        if isinstance(path, dict) and path.get("pathType") == 2
    ]

    if not transit_paths:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    path = transit_paths[0]

    duration = valid_number_or_none(path.get("totalTime"))
    distance = valid_number_or_none(path.get("totalDistance"))

    if duration is None or distance is None:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    arrival_time = path.get("endDateTime")

    if arrival_time:
        try:
            arrival_time = datetime.strptime(
                arrival_time,
                "%Y%m%d%H%M",
            ).replace(tzinfo=KST).isoformat()

        except (TypeError, ValueError):
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    else:
        arrival_time = (
            departure_time + timedelta(minutes=duration)
        ).isoformat()

    transit_path = build_transit_path(path)

    if not transit_path:
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

    return {
        "event_id": event.id,
        "mode": "transit",
        "departure_time": departure_time.isoformat(),
        "duration_minutes": duration,
        "distance_meters": distance,
        "arrival_time": arrival_time,
        "path": transit_path,
        "steps": build_transit_steps(path),
    }