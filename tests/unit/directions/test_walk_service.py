"""ODsay 도보 길찾기 테스트. requests.get은 모두 가짜."""
import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions.walk_service import build_walk_steps, get_walk_directions

ROUTES = [
    {"distance": 100, "duration": 60},
    {"distance": 200, "duration": 120},
    {"distance": 300, "duration": 300},
]


def guide(text, index, **extra):
    return {"guidance": text, "routeIndex": index, "point": [127.0, 36.0], "angle": 10,
            "turn": "STRAIGHT", "facility": None, **extra}


def payload(guides=None, routes=None, distance=600, duration=480, has_result=True, recommend=True):
    path = {"hasPathResult": has_result}
    if recommend:
        path["recommend"] = {
            "summary": {"distance": distance, "duration": duration},
            "guides": guides if guides is not None else [guide("직진", 0), guide("좌회전", 1)],
            "routes": routes if routes is not None else ROUTES,
        }
    return {"result": {"path": [path]}}


def code_of(exc_info):
    return exc_info.value.error_code


def call(event, departure):
    return get_walk_directions(event, 36.5, 127.0, departure)


def test_steps_sum_routes_until_next_guide():
    steps = build_walk_steps({"guides": [guide("직진", 0), guide("좌회전", 1)], "routes": ROUTES})

    assert [(s["instruction"], s["distance_meters"], s["duration_minutes"]) for s in steps] == [
        ("직진", 100, 1.0),
        ("좌회전", 500, 7.0),  # 마지막 guide는 끝까지 합산한다.
    ]
    assert steps[0]["type"] == "WALK"
    assert steps[0]["detail"] == {"point": [127.0, 36.0], "angle": 10, "turn": "STRAIGHT", "facility": None}


@pytest.mark.parametrize("bad_index", [99, -1, True, "0", None])
def test_guide_with_invalid_route_index_is_skipped(bad_index):
    steps = build_walk_steps({"guides": [guide("나쁜", bad_index), guide("직진", 0)], "routes": ROUTES})

    assert [s["instruction"] for s in steps] == ["직진"]
    assert steps[0]["step_number"] == 1


def test_guide_without_guidance_is_skipped():
    assert build_walk_steps({"guides": [guide("", 0)], "routes": ROUTES}) == []


def test_route_values_that_are_not_numbers_are_ignored_in_sums():
    routes = [{"distance": "x", "duration": True}, {"distance": 50, "duration": 30}]

    steps = build_walk_steps({"guides": [guide("직진", 0)], "routes": routes})

    assert (steps[0]["distance_meters"], steps[0]["duration_minutes"]) == (50, 0)


def test_success_builds_summary(keys, fake_get, event, departure):
    fake_get(payload())

    result = call(event, departure)

    assert result["mode"] == "walk"
    assert result["duration_minutes"] == 8
    assert result["distance_meters"] == 600
    assert result["arrival_time"] == "2026-11-06T12:08:00+09:00"
    assert len(result["steps"]) == 2


def test_request_params(keys, fake_get, event, departure):
    calls = fake_get(payload())

    call(event, departure)

    sent = calls[0]
    assert sent["url"].endswith("/searchWalkPathV2")
    assert sent["params"]["loc"] == "127.0,36.5,127.154,36.819"
    assert sent["params"]["apiKey"] == "odsay-test-key"
    assert sent["timeout"] == 10


def test_missing_key(ctx, monkeypatch, fake_get, event, departure):
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", None)
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
    [{"exc": requests.ConnectionError()}, {"status": 500}, {"json_error": ValueError()}, {"payload": ["x"]}],
)
def test_transport_errors_map_to_502(keys, fake_get, event, departure, kwargs):
    fake_get(**kwargs)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_ERROR


def test_error_body_currently_maps_to_502(keys, fake_get, event, departure):
    """ODsay가 200 + error 본문을 주면 사유와 무관하게 502다(경로 없음 계열 구분은 이슈 3)."""
    fake_get({"error": {"code": "-98", "msg": "출발지와 도착지가 너무 가깝습니다."}})

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.DIRECTIONS_API_ERROR


@pytest.mark.parametrize(
    "body",
    [
        {"result": {"path": []}},
        {"result": None},
        payload(has_result=False),
        payload(recommend=False),
        {"result": {"path": [{"hasPathResult": True, "recommend": {"summary": None}}]}},
        payload(distance=-1),
        payload(duration="abc"),
        payload(duration=True),
    ],
)
def test_unusable_route_maps_to_404(keys, fake_get, event, departure, body):
    fake_get(body)

    with pytest.raises(BusinessException) as exc:
        call(event, departure)

    assert code_of(exc) == ErrorCode.ROUTE_NOT_FOUND



def test_non_dict_guide_does_not_crash():
    assert build_walk_steps({"guides": ["x"], "routes": []}) == []



def test_non_dict_path_does_not_crash(keys, fake_get, event, departure):
    fake_get({"result": {"path": ["x"]}})

    with pytest.raises(BusinessException):
        call(event, departure)
