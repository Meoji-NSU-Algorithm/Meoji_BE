"""CORS: 허용한 FE 주소에서만 브라우저가 API 응답을 읽을 수 있는지 확인한다 (#77)."""

ALLOWED_ORIGIN = "http://localhost:5174"


def _preflight(client, origin):
    return client.options(
        "/api/events",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )


def test_preflight_allows_configured_origin_with_authorization(client):
    res = _preflight(client, ALLOWED_ORIGIN)

    assert res.headers.get("Access-Control-Allow-Origin") == ALLOWED_ORIGIN
    assert "authorization" in res.headers.get("Access-Control-Allow-Headers", "").lower()


def test_preflight_rejects_unknown_origin(client):
    res = _preflight(client, "http://evil.example.com")

    assert "Access-Control-Allow-Origin" not in res.headers


def test_actual_request_has_allow_origin_header(client):
    res = client.get("/api/health", headers={"Origin": ALLOWED_ORIGIN})

    assert res.headers.get("Access-Control-Allow-Origin") == ALLOWED_ORIGIN
