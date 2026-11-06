"""길찾기 HTTP 통합 테스트. 실제 앱/DB를 쓰고 외부 API(requests.get)만 가짜로 바꾼다."""
from unittest.mock import MagicMock

import pytest
import requests

from app.domains.directions import car_service, transit_service, walk_service

CAR_BODY = {"routes": [{
    "result_code": 0,
    "summary": {"duration": 1500, "distance": 12345},
    "sections": [{"guides": [{"guidance": "출발", "distance": 250, "duration": 180}]}],
}]}
WALK_BODY = {"result": {"path": [{"hasPathResult": True, "recommend": {
    "summary": {"distance": 600, "duration": 480},
    "guides": [{"guidance": "직진", "routeIndex": 0, "point": [127, 36], "angle": 1, "turn": "S", "facility": None}],
    "routes": [{"distance": 600, "duration": 480}],
}}]}}
TRANSIT_BODY = {"result": {"paths": [{
    "pathType": 2, "totalTime": 35, "totalDistance": 12000, "endDateTime": "202611061235",
    "rps": [{"trafficType": 1, "lane": [{"name": "2호선"}], "endName": "강남", "distance": 5000, "duration": 20}],
}]}}
QUERY = "originLat=36.5&originLng=127.0"


@pytest.fixture()
def keys(app_ctx, monkeypatch):
    monkeypatch.setitem(app_ctx.config, "KAKAO_CLIENT_ID", "kakao-test-key")
    monkeypatch.setitem(app_ctx.config, "ODSAY_API_KEY", "odsay-test-key")
    return app_ctx.config


@pytest.fixture()
def upstream(monkeypatch):
    """requests.get을 가짜로 바꾸는 설치 함수. 호출 기록을 돌려준다."""

    def install(payload=None, exc=None, status=200):
        calls = []

        def _get(url, **kwargs):
            calls.append({"url": url, **kwargs})
            if exc is not None:
                raise exc
            response = MagicMock()
            if status >= 400:
                response.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status))
            response.json.return_value = payload
            return response

        monkeypatch.setattr(requests, "get", _get)
        return calls

    return install


@pytest.fixture()
def auth(login):
    """실제 로그인 API로 받은 Authorization 헤더."""
    headers, _, _ = login()
    return headers


@pytest.fixture()
def located(make_event):
    """좌표가 있는 행사."""
    return make_event(latitude=36.819, longitude=127.154)


def error_of(response):
    body = response.get_json()
    assert body["success"] is False
    return body["code"]


# ---- 성공 ----
@pytest.mark.parametrize(
    "mode, body, extra",
    [
        ("car", CAR_BODY, {"type": "DRIVE", "duration": 25}),
        ("walk", WALK_BODY, {"type": "WALK", "duration": 8}),
        ("transit", TRANSIT_BODY, {"type": "SUBWAY", "duration": 35}),
    ],
)
def test_each_mode_returns_camel_case_envelope(client, auth, keys, upstream, located, mode, body, extra):
    upstream(body)

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode={mode}", headers=auth)

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["eventId"] == located.id
    assert data["mode"] == mode
    assert data["durationMinutes"] == extra["duration"]
    assert set(data) == {"eventId", "mode", "departureTime", "durationMinutes",
                         "distanceMeters", "arrivalTime", "steps"}
    assert data["steps"][0]["stepNumber"] == 1
    assert data["steps"][0]["type"] == extra["type"]


def test_mode_defaults_to_transit(client, auth, keys, upstream, located):
    calls = upstream(TRANSIT_BODY)

    response = client.get(f"/api/directions/{located.id}?{QUERY}", headers=auth)

    assert response.status_code == 200
    assert response.get_json()["data"]["mode"] == "transit"
    assert calls[0]["url"].endswith("/maasRP")


# ---- 서비스 분기 ----
@pytest.mark.parametrize(
    "mode, module, func",
    [
        ("car", car_service, "get_car_directions"),
        ("walk", walk_service, "get_walk_directions"),
        ("transit", transit_service, "get_transit_directions"),
    ],
)
def test_mode_dispatches_to_matching_service(client, auth, keys, monkeypatch, located, mode, module, func):
    seen = {}

    def fake(event, lat, lng, departure):
        seen.update(event_id=event.id, lat=lat, lng=lng, tz=departure.tzinfo is not None)
        return {"event_id": event.id, "mode": mode, "departure_time": "d", "duration_minutes": 1,
                "distance_meters": 1, "arrival_time": "a", "steps": []}

    monkeypatch.setattr(module, func, fake)

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode={mode}", headers=auth)

    assert response.status_code == 200
    assert seen == {"event_id": located.id, "lat": 36.5, "lng": 127.0, "tz": True}


# ---- 요청 검증 400 ----
@pytest.mark.parametrize(
    "query",
    [
        "originLng=127.0",
        "originLat=36.5",
        "originLat=91&originLng=127.0",
        "originLat=36.5&originLng=127.0&mode=bike",
        "originLat=36.5&originLng=127.0&toLat=37",
        "fromLat=36.5&fromLng=127.0&toLat=37&toLng=127",
        "originLat=36.5&originLat=37&originLng=127.0",
        "originLat=abc&originLng=127.0",
    ],
)
def test_invalid_query_returns_400(client, auth, keys, upstream, located, query):
    calls = upstream(CAR_BODY)

    response = client.get(f"/api/directions/{located.id}?{query}", headers=auth)

    assert response.status_code == 400
    assert error_of(response) == "COMMON_INVALID_INPUT"
    assert calls == []


def test_event_id_zero_returns_400(client, auth, keys):
    response = client.get(f"/api/directions/0?{QUERY}", headers=auth)

    assert response.status_code == 400


# ---- 404 ----
def test_unknown_event_returns_404(client, auth, keys):
    response = client.get(f"/api/directions/999999?{QUERY}", headers=auth)

    assert response.status_code == 404
    assert error_of(response) == "EVENT_NOT_FOUND"


def test_event_without_coordinates_returns_404(client, auth, keys, upstream, make_event):
    event = make_event()
    calls = upstream(CAR_BODY)

    response = client.get(f"/api/directions/{event.id}?{QUERY}&mode=car", headers=auth)

    assert response.status_code == 404
    assert error_of(response) == "ROUTE_NOT_FOUND"
    assert calls == []


def test_no_route_from_upstream_returns_404(client, auth, keys, upstream, located):
    upstream({"routes": []})

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode=car", headers=auth)

    assert response.status_code == 404
    assert error_of(response) == "ROUTE_NOT_FOUND"


# ---- 외부 장애 ----
def test_upstream_timeout_returns_504(client, auth, keys, upstream, located):
    upstream(exc=requests.Timeout())

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode=walk", headers=auth)

    assert response.status_code == 504
    assert error_of(response) == "DIRECTIONS_API_TIMEOUT"


@pytest.mark.parametrize("kwargs", [{"exc": requests.ConnectionError()}, {"status": 500}])
def test_upstream_failure_returns_502(client, auth, keys, upstream, located, kwargs):
    upstream(**kwargs)

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode=transit", headers=auth)

    assert response.status_code == 502
    assert error_of(response) == "DIRECTIONS_API_ERROR"


@pytest.mark.parametrize(
    "mode, config_key",
    [("car", "KAKAO_CLIENT_ID"), ("walk", "ODSAY_API_KEY"), ("transit", "ODSAY_API_KEY")],
)
def test_missing_api_key_returns_500_with_dedicated_code(client, auth, keys, monkeypatch, upstream, located, mode, config_key):
    monkeypatch.setitem(keys, config_key, None)
    calls = upstream(CAR_BODY)

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode={mode}", headers=auth)

    assert response.status_code == 500
    assert error_of(response) == "DIRECTIONS_API_KEY_MISSING"
    assert calls == []


# ---- 인증 ----
def test_without_token_returns_401_and_never_calls_upstream(client, keys, upstream, located):
    calls = upstream(CAR_BODY)

    response = client.get(f"/api/directions/{located.id}?{QUERY}&mode=car")

    assert response.status_code == 401
    assert calls == []


def test_invalid_token_returns_401(client, keys, upstream, located):
    upstream(CAR_BODY)

    response = client.get(
        f"/api/directions/{located.id}?{QUERY}&mode=car",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert response.status_code == 401
