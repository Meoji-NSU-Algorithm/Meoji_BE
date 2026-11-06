"""카카오모빌리티 자동차 길찾기 테스트. requests.get은 모두 가짜."""
import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions.car_service import build_car_steps, get_car_directions


def payload(duration=1500, distance=12345, guides=None, result_code=0):
    if guides is None:
        guides = [
            {"guidance": "출발", "distance": 250.4, "duration": 180},
            {"guidance": "", "distance": 1, "duration": 1},
            {"guidance": "우회전", "distance": 900, "duration": 90},
        ]
    return {"routes": [{
        "result_code": result_code,
        "summary": {"duration": duration, "distance": distance},
        "sections": [{"guides": guides}],
    }]}


def code_of(exc_info):
    return exc_info.value.error_code


def call(event, departure, **kw):
    return get_car_directions(event, kw.get("lat", 36.5), kw.get("lng", 127.0), departure)


def test_success_builds_summary_and_steps(keys, fake_get, event, departure):
    fake_get(payload())

    result = call(event, departure)

    assert result["event_id"] == 7
    assert result["mode"] == "car"
    assert result["duration_minutes"] == 25
    assert result["distance_meters"] == 12345
    assert result["departure_time"] == departure.isoformat()
    assert result["arrival_time"] == "2026-11-06T12:25:00+09:00"
    # guidance가 빈 guide는 건너뛰고 번호는 이어서 매긴다.
    assert [s["step_number"] for s in result["steps"]] == [1, 2]
    assert result["steps"][0] == {
        "step_number": 1, "type": "DRIVE", "instruction": "출발",
        "duration_minutes": 3, "distance_meters": 250, "detail": None,
    }


def test_request_uses_lng_lat_order_key_header_and_timeout(keys, fake_get, event, departure):
    calls = fake_get(payload())

    call(event, departure, lat=36.5, lng=127.0)

    sent = calls[0]
    assert sent["params"]["origin"] == "127.0,36.5"
    assert sent["params"]["destination"] == "127.154,36.819"
    assert sent["headers"]["Authorization"] == "KakaoAK kakao-test-key"
    assert sent["timeout"] == 10


def test_missing_key_is_reported_before_any_request(ctx, monkeypatch, fake_get, event, departure):
    monkeypatch.setitem(ctx.config, "KAKAO_CLIENT_ID", None)
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
    [
        {"exc": requests.ConnectionError()},
        {"status": 401},
        {"status": 500},
        {"json_error": ValueError("not json")},
    ],
)
def test_transport_errors_map_to_502(keys, fake_get, event, departure, kwargs):
    fake_get(**kwargs)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_ERROR


@pytest.mark.parametrize(
    "body",
    [
        {"routes": []},
        {"routes": None},
        {},
        ["not", "a", "dict"],
        payload(result_code=104),
        {"routes": ["x"]},
        {"routes": [{"result_code": 0}]},
        payload(duration=-1),
        payload(duration=True),
        payload(duration="abc"),
        payload(distance=-5),
        payload(distance=float("nan")),
        payload(distance=None),
    ],
)
def test_unusable_route_maps_to_404(keys, fake_get, event, departure, body):
    fake_get(body)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.ROUTE_NOT_FOUND


def test_step_values_that_are_not_valid_numbers_become_none():
    route = {"sections": [{"guides": [
        {"guidance": "a", "distance": -1, "duration": "x"},
        {"guidance": "b", "distance": True, "duration": float("inf")},
        {"guidance": "c"},
    ]}]}

    steps = build_car_steps(route)

    assert [(s["distance_meters"], s["duration_minutes"]) for s in steps] == [(None, None)] * 3


def test_no_sections_gives_no_steps():
    assert build_car_steps({}) == []
