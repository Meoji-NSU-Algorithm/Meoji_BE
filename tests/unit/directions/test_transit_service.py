import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import transit_service


def good_path():
    return {
        "pathType": 2, "totalTime": 40, "totalDistance": 12000, "endDateTime": "202601011000",
        "rps": [
            {"trafficType": 3, "distance": 100, "duration": 2,
             "guides": [{"GUIDANCE": "직진"}, {"GUIDANCE": "좌회전"}],
             "routes": [{"xyInfos": [{"x": 127.0, "y": 36.0}]}]},
            {"trafficType": 1, "distance": 5000, "duration": 15, "endName": "천안", "way": "신창",
             "startExitNo": "1", "endExitNo": "2", "lane": [{"name": "1호선"}],
             "graph": "127.1 36.1|127.2 36.2"},
            {"trafficType": 2, "distance": 6000, "duration": 20, "startName": "A", "endName": "B",
             "lane": [{"busNo": 100}], "passStopList": {"stations": [1, 2]},
             "graph": "127.3 36.3"},
        ],
    }


def good():
    return {"result": {"paths": [{"pathType": 1}, good_path()]}}


def code(*a):
    with pytest.raises(BusinessException) as ei:
        transit_service.get_transit_directions(*a)
    return ei.value.error_code


def test_success(ctx, event, departure, fake_request):
    calls = fake_request(transit_service, good())
    r = transit_service.get_transit_directions(event, 37.0, 127.0, departure)
    assert r["mode"] == "transit" and r["duration_minutes"] == 40 and r["distance_meters"] == 12000
    assert r["arrival_time"] == "2026-01-01T10:00:00+09:00"
    assert [p["type"] for p in r["path"]] == ["WALK", "SUBWAY", "BUS"]
    assert r["path"][1]["coordinates"] == [[36.1, 127.1], [36.2, 127.2]]
    assert [s["type"] for s in r["steps"]] == ["WALK", "SUBWAY", "BUS"]
    p = calls[0]["params"]
    assert p["SX"] == 127.0 and p["SY"] == 37.0 and p["EX"] == 127.1 and p["EY"] == 36.8
    assert p["SearchTime"] == "202601010900" and p["apiKey"] == "odsay-key"


def test_arrival_computed_when_missing(ctx, event, departure, fake_request):
    d = good()
    del d["result"]["paths"][1]["endDateTime"]
    fake_request(transit_service, d)
    r = transit_service.get_transit_directions(event, 37.0, 127.0, departure)
    assert r["arrival_time"] == "2026-01-01T09:40:00+09:00"


def test_bad_end_datetime(ctx, event, departure, fake_request):
    d = good()
    d["result"]["paths"][1]["endDateTime"] = "garbage"
    fake_request(transit_service, d)
    assert code(event, 1, 2, departure) == ErrorCode.ROUTE_NOT_FOUND


def test_missing_key(ctx, event, departure, monkeypatch, fake_request):
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", "")
    fake_request(transit_service, good())
    assert code(event, 1, 2, departure) == ErrorCode.DIRECTIONS_API_KEY_MISSING


def test_odsay_error_field(ctx, event, departure, fake_request):
    fake_request(transit_service, {"error": {"code": "500"}})
    assert code(event, 1, 2, departure) == ErrorCode.DIRECTIONS_API_ERROR


def mutate(fn):
    d = good()
    fn(d["result"]["paths"][1])
    return d


@pytest.mark.parametrize("payload", [
    {}, {"result": []}, {"result": {"paths": []}}, {"result": {"paths": "x"}},
    {"result": {"paths": [{"pathType": 1}, "x"]}},
    mutate(lambda p: p.pop("totalTime")),
    mutate(lambda p: p.update(totalDistance=-3)),
    mutate(lambda p: p.update(rps=[])),
    mutate(lambda p: p.update(rps=[{"trafficType": 9}])),
])
def test_route_not_found(ctx, event, departure, fake_request, payload):
    fake_request(transit_service, payload)
    assert code(event, 1, 2, departure) == ErrorCode.ROUTE_NOT_FOUND


@pytest.mark.parametrize("exc_code", [ErrorCode.DIRECTIONS_API_TIMEOUT, ErrorCode.DIRECTIONS_API_ERROR])
def test_upstream_errors_propagate(ctx, event, departure, fake_request, exc_code):
    fake_request(transit_service, BusinessException(exc_code))
    assert code(event, 1, 2, departure) == exc_code


def test_step_instructions():
    steps = transit_service.build_transit_steps(good_path())
    assert steps[0]["instruction"] == "직진 → 좌회전"
    assert steps[1]["instruction"] == "1호선 탑승, 천안역 하차 (신창 방면)"
    assert steps[1]["detail"] == "출발역 1번 출구, 도착역 2번 출구"
    assert steps[2]["instruction"] == "100번 버스 이용: A 승차 → B 하차"
    assert steps[2]["detail"] == "경유 정류장 정보 2개"
    assert [s["step_number"] for s in steps] == [1, 2, 3]


def test_step_defaults_and_other():
    path = {"rps": ["x", {"trafficType": 1}, {"trafficType": 2, "startName": "A"},
                    {"trafficType": 2, "endName": "B"}, {"trafficType": 3}, {"trafficType": 7},
                    {"trafficType": 2, "lane": "x", "distance": -1}]}
    s = transit_service.build_transit_steps(path)
    assert s[0]["instruction"] == "지하철 탑승" and s[0]["detail"] is None
    assert s[1]["instruction"] == "버스번 버스 이용: A 승차"
    assert s[2]["instruction"].endswith(": B 하차")
    assert s[3]["instruction"] == "도보 이동"
    assert s[4]["type"] == "OTHER" and s[4]["instruction"] == "이동"
    assert s[5]["distance_meters"] is None
    assert transit_service.build_transit_steps({"rps": "x"}) == []


def test_path_invalid_graph_and_routes():
    path = {"rps": [
        {"trafficType": 1, "graph": "bad|1 2 3|127.0 36.0|-1 5"},
        {"trafficType": 2, "graph": 5},
        {"trafficType": 3, "routes": "x"},
        {"trafficType": 3, "routes": ["x", {"xyInfos": "x"}, {"xyInfos": ["x", {"x": 1, "y": 2}]}]},
        {"trafficType": 9, "graph": "1 2"}, "x",
    ]}
    out = transit_service.build_transit_path(path)
    assert out == [{"type": "SUBWAY", "coordinates": [[36.0, 127.0]]},
                   {"type": "WALK", "coordinates": [[2, 1]]}]
    assert transit_service.build_transit_path({"rps": 1}) == []
