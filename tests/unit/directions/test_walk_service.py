import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import walk_service


def good():
    return {"result": {"path": [{"hasPathResult": True, "recommend": {
        "summary": {"distance": 300, "duration": 270},
        "routes": [
            {"distance": 100, "duration": 90, "coordinate": [{"x": 127.1, "y": 36.8}]},
            {"distance": 200, "duration": 180, "coordinate": [{"x": 127.2, "y": 36.9}]},
        ],
        "guides": [
            {"guidance": "직진", "routeIndex": 0, "point": "p", "angle": 1, "turn": 0, "facility": None},
            {"guidance": "도착", "routeIndex": 1},
        ],
    }}]}}


def code(*a):
    with pytest.raises(BusinessException) as ei:
        walk_service.get_walk_directions(*a)
    return ei.value.error_code


def test_success(ctx, event, departure, fake_request):
    calls = fake_request(walk_service, good())
    r = walk_service.get_walk_directions(event, 37.0, 127.0, departure)
    assert r["mode"] == "walk" and r["duration_minutes"] == 4  # round(270/60)=round(4.5)=4
    assert r["distance_meters"] == 300
    assert r["path"] == [[36.8, 127.1], [36.9, 127.2]]
    assert r["arrival_time"] == "2026-01-01T09:04:30+09:00"
    assert [s["instruction"] for s in r["steps"]] == ["직진", "도착"]
    assert r["steps"][0]["distance_meters"] == 100 and r["steps"][0]["duration_minutes"] == 1.5
    assert r["steps"][0]["detail"]["point"] == "p"
    c = calls[0]
    assert c["params"]["loc"] == "127.0,37.0,127.1,36.8"
    assert c["params"]["apiKey"] == "odsay-key" and c["headers"] is None


def test_missing_key(ctx, event, departure, monkeypatch, fake_request):
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", None)
    fake_request(walk_service, good())
    assert code(event, 1, 2, departure) == ErrorCode.DIRECTIONS_API_KEY_MISSING


def test_odsay_error_field(ctx, event, departure, fake_request):
    fake_request(walk_service, {"error": {"code": "-8", "msg": "x"}})
    assert code(event, 1, 2, departure) == ErrorCode.DIRECTIONS_API_ERROR


def mutate(fn):
    d = good()
    fn(d["result"]["path"][0])
    return d


@pytest.mark.parametrize("payload", [
    {}, {"result": "x"}, {"result": {}}, {"result": {"path": []}},
    {"result": {"path": ["x"]}},
    mutate(lambda p: p.update(hasPathResult=False)),
    mutate(lambda p: p.pop("recommend")),
    mutate(lambda p: p["recommend"].pop("summary")),
    mutate(lambda p: p["recommend"]["summary"].update(distance=-1)),
    mutate(lambda p: p["recommend"]["summary"].pop("duration")),
    mutate(lambda p: p["recommend"].update(routes=[])),
])
def test_route_not_found(ctx, event, departure, fake_request, payload):
    fake_request(walk_service, payload)
    assert code(event, 1, 2, departure) == ErrorCode.ROUTE_NOT_FOUND


@pytest.mark.parametrize("exc_code", [ErrorCode.DIRECTIONS_API_TIMEOUT, ErrorCode.DIRECTIONS_API_ERROR])
def test_upstream_errors_propagate(ctx, event, departure, fake_request, exc_code):
    fake_request(walk_service, BusinessException(exc_code))
    assert code(event, 1, 2, departure) == exc_code


def test_steps_invalid_inputs():
    assert walk_service.build_walk_steps({"guides": "x", "routes": []}) == []
    assert walk_service.build_walk_steps({"guides": [], "routes": "x"}) == []
    rd = {"routes": [{"distance": 10, "duration": 60}], "guides": [
        "x", {"guidance": "", "routeIndex": 0}, {"guidance": "a", "routeIndex": True},
        {"guidance": "a", "routeIndex": 5}, {"guidance": "a", "routeIndex": -1},
        {"guidance": "ok", "routeIndex": 0},
    ]}
    steps = walk_service.build_walk_steps(rd)
    assert len(steps) == 1 and steps[0]["step_number"] == 1
    assert steps[0]["distance_meters"] == 10


def test_steps_sum_until_next_guide():
    rd = {"routes": [{"distance": 1, "duration": 60}, {"distance": 2, "duration": 60}, {"distance": 4, "duration": 60}],
          "guides": [{"guidance": "a", "routeIndex": 0}, {"guidance": "b", "routeIndex": 2}]}
    s = walk_service.build_walk_steps(rd)
    assert s[0]["distance_meters"] == 3 and s[0]["duration_minutes"] == 2.0
    assert s[1]["distance_meters"] == 4


def test_path_filters():
    rd = {"routes": ["x", {"coordinate": "x"}, {"coordinate": ["x", {"x": -1, "y": 1}, {"x": 1, "y": 2}]}]}
    assert walk_service.build_walk_path(rd) == [[2, 1]]
    assert walk_service.build_walk_path({"routes": "x"}) == []
