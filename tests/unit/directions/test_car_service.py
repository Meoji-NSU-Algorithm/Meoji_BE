import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import car_service


def good():
    return {"routes": [{
        "result_code": 0,
        "summary": {"duration": 600, "distance": 5000},
        "sections": [{
            "roads": [{"vertexes": [127.1, 36.8, 127.2, 36.9]}],
            "guides": [{"guidance": "출발", "distance": 100, "duration": 90}],
        }],
    }]}


def code(fn, *a):
    with pytest.raises(BusinessException) as ei:
        fn(*a)
    return ei.value.error_code


def test_success(ctx, event, departure, fake_request):
    calls = fake_request(car_service, good())
    r = car_service.get_car_directions(event, 37.0, 127.0, departure)
    assert r["mode"] == "car" and r["event_id"] == 7
    assert r["duration_minutes"] == 10 and r["distance_meters"] == 5000
    assert r["path"] == [[36.8, 127.1], [36.9, 127.2]]  # [lat, lng]
    assert r["arrival_time"] == "2026-01-01T09:10:00+09:00"
    assert r["steps"] == [{"step_number": 1, "type": "DRIVE", "instruction": "출발",
                           "duration_minutes": 2, "distance_meters": 100, "detail": None}]
    c = calls[0]
    assert c["params"] == {"origin": "127.0,37.0", "destination": "127.1,36.8"}
    assert c["headers"] == {"Authorization": "KakaoAK kakao-key"}


def test_missing_key(ctx, event, departure, monkeypatch, fake_request):
    monkeypatch.setitem(ctx.config, "KAKAO_CLIENT_ID", None)
    fake_request(car_service, good())
    assert code(car_service.get_car_directions, event, 1, 2, departure) == ErrorCode.DIRECTIONS_API_KEY_MISSING


@pytest.mark.parametrize("payload", [
    {}, {"routes": []}, {"routes": "x"}, {"routes": ["x"]},
    {"routes": [{"result_code": 104}]},
    {"routes": [{"result_code": 0}]},
    {"routes": [{"result_code": 0, "summary": {"duration": -1, "distance": 1}}]},
    {"routes": [{"result_code": 0, "summary": {"duration": 1}}]},
    {"routes": [{"result_code": 0, "summary": {"duration": 1, "distance": 1}, "sections": []}]},
])
def test_route_not_found(ctx, event, departure, fake_request, payload):
    fake_request(car_service, payload)
    assert code(car_service.get_car_directions, event, 1, 2, departure) == ErrorCode.ROUTE_NOT_FOUND


@pytest.mark.parametrize("exc_code", [ErrorCode.DIRECTIONS_API_TIMEOUT, ErrorCode.DIRECTIONS_API_ERROR])
def test_upstream_errors_propagate(ctx, event, departure, fake_request, exc_code):
    fake_request(car_service, BusinessException(exc_code))
    assert code(car_service.get_car_directions, event, 1, 2, departure) == exc_code


def test_steps_skip_bad_guides_and_null_invalid_numbers():
    route = {"sections": [
        "x",
        {"guides": "x"},
        {"guides": [
            "x", {"guidance": ""}, {"guidance": 3},
            {"guidance": "a", "distance": -5, "duration": "x"},
            {"guidance": "b", "distance": 10.6, "duration": 89},
        ]},
    ]}
    steps = car_service.build_car_steps(route)
    assert [s["step_number"] for s in steps] == [1, 2]
    assert steps[0]["duration_minutes"] is None and steps[0]["distance_meters"] is None
    assert steps[1]["distance_meters"] == 11 and steps[1]["duration_minutes"] == 1


def test_steps_bad_sections_type():
    assert car_service.build_car_steps({"sections": "x"}) == []
    assert car_service.build_car_steps({}) == []


def test_path_odd_vertexes_and_invalid():
    route = {"sections": [{"roads": [
        {"vertexes": [127.0, 36.0, 127.1]},          # 홀수 -> 마지막 무시
        {"vertexes": [-1, 5, 127.2, 36.2]},          # 음수 거부
        {"vertexes": "x"}, "x",
    ]}, {"roads": "x"}, "x"]}
    assert car_service.build_car_path(route) == [[36.0, 127.0], [36.2, 127.2]]
    assert car_service.build_car_path({"sections": 1}) == []
