"""GET /api/directions/<event_id> HTTP 흐름. 카카오 모빌리티/ODsay 는 client.request_json 을 가짜로 바꿔 절대 호출하지 않는다."""
import re
from decimal import Decimal

import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.directions import car_service, transit_service, walk_service

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")
Q = {"originLat": "37.5", "originLng": "127.0"}


@pytest.fixture(autouse=True)
def keys_and_no_network(app, monkeypatch):
    monkeypatch.setitem(app.config, "KAKAO_CLIENT_ID", "kakao-key")
    monkeypatch.setitem(app.config, "ODSAY_API_KEY", "odsay-key")

    def boom(*a, **kw):
        raise AssertionError("실제 외부 API 호출 금지")

    monkeypatch.setattr(requests, "get", boom)


CAR = {"routes": [{"result_code": 0, "summary": {"duration": 600, "distance": 5000},
                   "sections": [{"roads": [{"vertexes": [127.1, 36.8, 127.2, 36.9]}],
                                 "guides": [{"guidance": "출발", "distance": 100, "duration": 60}]}]}]}
WALK = {"result": {"path": [{"hasPathResult": True, "recommend": {
    "summary": {"distance": 300, "duration": 300},
    "routes": [{"distance": 300, "duration": 300, "coordinate": [{"x": 127.1, "y": 36.8}]}],
    "guides": [{"guidance": "직진", "routeIndex": 0}]}}]}}
TRANSIT = {"result": {"paths": [{"pathType": 2, "totalTime": 30, "totalDistance": 9000,
                                 "endDateTime": "202601011000",
                                 "rps": [{"trafficType": 1, "distance": 9000, "duration": 30,
                                          "lane": [{"name": "1호선"}], "graph": "127.1 36.8|127.2 36.9"}]}]}}


@pytest.fixture()
def upstream(monkeypatch):
    """모드별 payload(또는 예외)를 지정하는 함수. 호출 기록 리스트를 돌려준다."""
    calls = []

    def install(car=CAR, walk=WALK, transit=TRANSIT):
        for mod, payload in ((car_service, car), (walk_service, walk), (transit_service, transit)):
            def fake(url, params, headers=None, _p=payload, _m=mod.__name__):
                calls.append((_m, url))
                if isinstance(_p, Exception):
                    raise _p
                return _p
            monkeypatch.setattr(mod, "request_json", fake)
        return calls

    return install


@pytest.fixture()
def event_id(make_event):
    e = make_event()
    e.latitude, e.longitude = Decimal("36.8"), Decimal("127.1")
    db.session.commit()
    return e.id


def assert_err(resp, status, code):
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is False and body["code"] == code
    assert UPPER_SNAKE.match(body["code"])
    assert isinstance(body["message"], str) and body["message"]
    assert "data" not in body
    return body


@pytest.mark.parametrize("mode,payload_name", [("car", "car"), ("walk", "walk"), ("transit", "transit"), (None, "transit")])
def test_success_per_mode(client, login, upstream, event_id, mode, payload_name):
    upstream()
    headers, _, _ = login()
    q = dict(Q, **({"mode": mode} if mode else {}))
    resp = client.get(f"/api/directions/{event_id}", query_string=q, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["success"] is True
    d = body["data"]
    assert d["eventId"] == event_id and d["mode"] == payload_name
    for key in ("departureTime", "durationMinutes", "distanceMeters", "arrivalTime", "path", "steps"):
        assert key in d
    assert d["path"] and d["steps"]
    assert {"stepNumber", "type", "instruction", "durationMinutes", "distanceMeters", "detail"} <= set(d["steps"][0])


def test_car_path_is_lat_lng(client, login, upstream, event_id):
    upstream()
    headers, _, _ = login()
    d = client.get(f"/api/directions/{event_id}", query_string=dict(Q, mode="car"), headers=headers).get_json()["data"]
    assert d["path"][0] == [36.8, 127.1]


def test_requires_auth(client, upstream, event_id):
    calls = upstream()
    assert_err(client.get(f"/api/directions/{event_id}", query_string=Q), 401, "AUTH_UNAUTHORIZED")
    assert calls == []


def test_invalid_token(client, upstream, event_id, bearer):
    upstream()
    resp = client.get(f"/api/directions/{event_id}", query_string=Q, headers=bearer("garbage"))
    assert_err(resp, 401, "AUTH_TOKEN_INVALID")


@pytest.mark.parametrize("query", [
    {}, {"originLat": "37.5"}, {"originLng": "127"},
    {"originLat": "abc", "originLng": "127"},
    {"originLat": "91", "originLng": "127"},
    {"originLat": "37", "originLng": "181"},
    {"originLat": "37", "originLng": "127", "mode": "bike"},
    {"originLat": "37", "originLng": "127", "unknown": "1"},
])
def test_validation_errors(client, login, upstream, event_id, query):
    calls = upstream()
    headers, _, _ = login()
    assert_err(client.get(f"/api/directions/{event_id}", query_string=query, headers=headers), 400, "COMMON_INVALID_INPUT")
    assert calls == []


def test_duplicate_query_key(client, login, upstream, event_id):
    upstream()
    headers, _, _ = login()
    resp = client.get(f"/api/directions/{event_id}?originLat=1&originLat=2&originLng=3", headers=headers)
    assert_err(resp, 400, "COMMON_INVALID_INPUT")


@pytest.mark.parametrize("eid", [0, 2147483648])
def test_event_id_out_of_range(client, login, upstream, eid):
    upstream()
    headers, _, _ = login()
    assert_err(client.get(f"/api/directions/{eid}", query_string=Q, headers=headers), 400, "COMMON_INVALID_INPUT")


def test_non_integer_event_id_is_404(client, login):
    headers, _, _ = login()
    assert_err(client.get("/api/directions/abc", query_string=Q, headers=headers), 404, "COMMON_NOT_FOUND")


def test_event_not_found(client, login, upstream):
    upstream()
    headers, _, _ = login()
    assert_err(client.get("/api/directions/999999", query_string=Q, headers=headers), 404, "EVENT_NOT_FOUND")


def test_event_without_coordinates(client, login, upstream, make_event):
    calls = upstream()
    e = make_event()
    headers, _, _ = login()
    assert_err(client.get(f"/api/directions/{e.id}", query_string=Q, headers=headers), 404, "ROUTE_NOT_FOUND")
    assert calls == []


@pytest.mark.parametrize("mode", ["car", "walk", "transit"])
def test_no_route_from_upstream(client, login, upstream, event_id, mode):
    upstream(car={"routes": []}, walk={"result": {"path": []}}, transit={"result": {"paths": []}})
    headers, _, _ = login()
    resp = client.get(f"/api/directions/{event_id}", query_string=dict(Q, mode=mode), headers=headers)
    assert_err(resp, 404, "ROUTE_NOT_FOUND")


@pytest.mark.parametrize("exc,status,code", [
    (BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT), 504, "DIRECTIONS_API_TIMEOUT"),
    (BusinessException(ErrorCode.DIRECTIONS_API_ERROR), 502, "DIRECTIONS_API_ERROR"),
])
@pytest.mark.parametrize("mode", ["car", "walk", "transit"])
def test_upstream_failure_mapping(client, login, upstream, event_id, mode, exc, status, code):
    upstream(car=exc, walk=exc, transit=exc)
    headers, _, _ = login()
    resp = client.get(f"/api/directions/{event_id}", query_string=dict(Q, mode=mode), headers=headers)
    assert_err(resp, status, code)


@pytest.mark.parametrize("exc,status,code", [
    (requests.Timeout(), 504, "DIRECTIONS_API_TIMEOUT"),
    (requests.ConnectionError(), 502, "DIRECTIONS_API_ERROR"),
])
@pytest.mark.parametrize("mode", ["car", "walk", "transit"])
def test_real_client_with_faked_requests(client, login, event_id, monkeypatch, mode, exc, status, code):
    """request_json 자체는 실제 코드를 타고, requests.get 만 예외를 던진다."""
    def fake_get(*a, **kw):
        raise exc

    monkeypatch.setattr(requests, "get", fake_get)
    headers, _, _ = login()
    resp = client.get(f"/api/directions/{event_id}", query_string=dict(Q, mode=mode), headers=headers)
    assert_err(resp, status, code)


def test_upstream_bad_json_body(client, login, event_id, monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return ["not", "a", "dict"]

    monkeypatch.setattr(requests, "get", lambda *a, **k: R())
    headers, _, _ = login()
    assert_err(client.get(f"/api/directions/{event_id}", query_string=Q, headers=headers), 502, "DIRECTIONS_API_ERROR")


@pytest.mark.parametrize("mode,key", [("car", "KAKAO_CLIENT_ID"), ("walk", "ODSAY_API_KEY"), ("transit", "ODSAY_API_KEY")])
def test_missing_api_key(client, login, app, monkeypatch, event_id, mode, key):
    monkeypatch.setitem(app.config, key, None)
    headers, _, _ = login()
    resp = client.get(f"/api/directions/{event_id}", query_string=dict(Q, mode=mode), headers=headers)
    assert_err(resp, 500, "DIRECTIONS_API_KEY_MISSING")


def test_wrong_method(client, login, event_id):
    headers, _, _ = login()
    resp = client.post(f"/api/directions/{event_id}", headers=headers)
    assert_err(resp, 405, "COMMON_METHOD_NOT_ALLOWED")
