"""ODsay 대중교통 길찾기 테스트. requests.get은 모두 가짜."""
import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions.schemas import DirectionsStepSchema
from app.domains.directions.transit_service import build_transit_steps, get_transit_directions


def path(**kw):
    base = {"pathType": 2, "totalTime": 35, "totalDistance": 12000,
            "endDateTime": "202611061235", "rps": []}
    base.update(kw)
    return base


def payload(*paths):
    return {"result": {"paths": list(paths) or [path()]}}


def code_of(exc_info):
    return exc_info.value.error_code


def call(event, departure):
    return get_transit_directions(event, 36.5, 127.0, departure)


def one_step(**part):
    return build_transit_steps({"rps": [part]})[0]


def test_subway_step():
    step = one_step(trafficType=1, lane=[{"name": "2호선"}], endName="강남", way="잠실",
                    startExitNo="3", endExitNo="5", distance=5000, duration=20)

    assert step["type"] == "SUBWAY"
    assert step["instruction"] == "2호선 탑승, 강남역 하차 (잠실 방면)"
    assert step["detail"] == "출발역 3번 출구, 도착역 5번 출구"
    assert (step["duration_minutes"], step["distance_meters"]) == (20, 5000)


def test_subway_without_lane_name_uses_default_label():
    assert one_step(trafficType=1)["instruction"] == "지하철 탑승"


def test_bus_step():
    step = one_step(trafficType=2, lane=[{"busNo": 400}, {"busNo": "401"}], startName="A", endName="B",
                    passStopList={"stations": [1, 2, 3]})

    assert step["type"] == "BUS"
    assert step["instruction"] == "400, 401번 버스 이용: A 승차 → B 하차"
    assert step["detail"] == "경유 정류장 정보 3개"


@pytest.mark.parametrize(
    "part, expected",
    [
        ({"startName": "A"}, "버스번 버스 이용: A 승차"),
        ({"endName": "B"}, "버스번 버스 이용: B 하차"),
        ({}, "버스번 버스 이용"),
    ],
)
def test_bus_step_without_bus_number_or_with_one_stop_name(part, expected):
    # 노선 번호가 없으면 "버스"가 번호 자리에 들어가 "버스번"이 된다(현재 동작을 그대로 고정).
    assert one_step(trafficType=2, **part)["instruction"] == expected


def test_walk_step_joins_guidance_or_falls_back():
    joined = one_step(trafficType=3, guides=[{"GUIDANCE": "직진"}, {"GUIDANCE": "횡단"}, {}, "x"])
    plain = one_step(trafficType=3)

    assert joined["type"] == "WALK"
    assert joined["instruction"] == "직진 → 횡단"
    assert plain["instruction"] == "도보 이동"
    assert plain["detail"] is None


def test_unknown_traffic_type_is_other():
    step = one_step(trafficType=9)

    assert (step["type"], step["instruction"]) == ("OTHER", "이동")


def test_steps_are_numbered_in_order():
    steps = build_transit_steps({"rps": [{"trafficType": 3}, {"trafficType": 2}, {"trafficType": 1}]})

    assert [(s["step_number"], s["type"]) for s in steps] == [(1, "WALK"), (2, "BUS"), (3, "SUBWAY")]


def test_success_uses_end_date_time_as_arrival(keys, fake_get, event, departure):
    fake_get(payload())

    result = call(event, departure)

    assert result["mode"] == "transit"
    assert result["duration_minutes"] == 35
    assert result["distance_meters"] == 12000
    assert result["arrival_time"] == "2026-11-06T12:35:00+09:00"
    assert result["departure_time"] == departure.isoformat()


def test_arrival_is_computed_when_end_date_time_missing(keys, fake_get, event, departure):
    fake_get(payload(path(endDateTime=None)))

    assert call(event, departure)["arrival_time"] == "2026-11-06T12:35:00+09:00"


def test_only_path_type_2_is_used(keys, fake_get, event, departure):
    fake_get(payload(path(pathType=1, totalTime=1), path(pathType=2, totalTime=40, endDateTime=None)))

    assert call(event, departure)["duration_minutes"] == 40


def test_request_params(keys, fake_get, event, departure):
    calls = fake_get(payload())

    call(event, departure)

    sent = calls[0]
    assert sent["url"].endswith("/maasRP")
    assert sent["params"]["SearchTime"] == "202611061200"
    assert (sent["params"]["SX"], sent["params"]["SY"]) == (127.0, 36.5)
    assert (sent["params"]["EX"], sent["params"]["EY"]) == (127.154, 36.819)
    assert sent["params"]["apiKey"] == "odsay-test-key"
    assert sent["timeout"] == 10


def test_missing_key(ctx, monkeypatch, fake_get, event, departure):
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", "")
    calls = fake_get(payload())

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_KEY_MISSING
    assert calls == []


def test_timeout_maps_to_504(keys, fake_get, event, departure):
    fake_get(exc=requests.Timeout())

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_TIMEOUT


@pytest.mark.parametrize(
    "kwargs",
    [{"exc": requests.ConnectionError()}, {"status": 503}, {"json_error": ValueError()},
     {"payload": []}, {"payload": {"error": {"code": "500"}}}],
)
def test_transport_and_error_body_map_to_502(keys, fake_get, event, departure, kwargs):
    fake_get(**kwargs)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_ERROR


@pytest.mark.parametrize(
    "body",
    [
        {"result": {"paths": []}},
        {"result": None},
        payload(path(pathType=1)),
        payload(path(totalTime=-1)),
        payload(path(totalTime="abc")),
        payload(path(totalDistance=None)),
        payload(path(endDateTime="not-a-date")),
        payload("x"),
    ],
)
def test_unusable_route_maps_to_404(keys, fake_get, event, departure, body):
    fake_get(body)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.ROUTE_NOT_FOUND


def test_step_with_non_numeric_duration_can_be_serialized():
    step = one_step(trafficType=3, duration="abc")

    DirectionsStepSchema().dump(step)
