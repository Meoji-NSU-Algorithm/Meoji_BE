"""모든 에러 응답이 공통 envelope(success/code/message)와 UPPER_SNAKE code를 따르는지 확인한다."""
import re
from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from app.core.errors import ErrorCode

UPPER_SNAKE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


def assert_envelope(resp, status, code):
    """에러 응답의 상태/envelope/code 형식을 확인하고 바디를 돌려준다."""
    body = resp.get_json()
    assert resp.status_code == status, body
    assert resp.is_json
    assert body["success"] is False
    assert body["code"] == code
    assert UPPER_SNAKE.match(body["code"])
    assert isinstance(body["message"], str) and body["message"]
    assert "data" not in body
    return body


def test_unknown_route_returns_404_envelope(client):
    """없는 경로는 404 COMMON_NOT_FOUND."""
    assert_envelope(client.get("/api/nope"), 404, "COMMON_NOT_FOUND")
    assert_envelope(client.get("/api/event"), 404, "COMMON_NOT_FOUND")
    assert_envelope(client.get("/nothing"), 404, "COMMON_NOT_FOUND")


def test_wrong_method_returns_405_with_allow_header(client):
    """허용되지 않은 메서드는 405와 Allow 헤더."""
    resp = client.delete("/api/events")
    assert_envelope(resp, 405, "COMMON_METHOD_NOT_ALLOWED")
    allow = {m.strip() for m in resp.headers["Allow"].split(",")}
    assert "GET" in allow and "DELETE" not in allow


def test_validation_error_has_errors_extra(client):
    """검증 실패는 400 COMMON_INVALID_INPUT과 필드별 errors."""
    body = assert_envelope(client.get("/api/events?page=0"), 400, "COMMON_INVALID_INPUT")
    assert "page" in body["errors"]
    body = assert_envelope(client.get("/api/events?unknown=1"), 400, "COMMON_INVALID_INPUT")
    assert "unknown" in body["errors"]


def test_business_error_returns_404_envelope(client, app_ctx):
    """비즈니스 예외(행사 없음)는 404 EVENT_NOT_FOUND."""
    assert_envelope(client.get("/api/events/999999"), 404, "EVENT_NOT_FOUND")


def test_expired_access_token_returns_401(client, app_ctx):
    """만료된 토큰은 401 AUTH_TOKEN_EXPIRED."""
    token = create_access_token(identity="1", expires_delta=timedelta(seconds=-10))
    resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert_envelope(resp, 401, "AUTH_TOKEN_EXPIRED")


def test_invalid_and_missing_token_return_401(client):
    """토큰이 없거나 위조면 401 envelope."""
    assert_envelope(client.get("/api/reviews/my"), 401, "AUTH_UNAUTHORIZED")
    resp = client.get("/api/reviews/my", headers={"Authorization": "Bearer bad.token.value"})
    assert_envelope(resp, 401, "AUTH_TOKEN_INVALID")


def test_token_for_deleted_user_returns_404(client, app_ctx):
    """유효한 토큰이지만 유저가 없으면 404 USER_NOT_FOUND."""
    token = create_access_token(identity="424242")
    resp = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert_envelope(resp, 404, "USER_NOT_FOUND")


def test_unexpected_exception_returns_500_without_details(app, client, monkeypatch):
    """예상 못한 예외는 500 COMMON_INTERNAL_ERROR이며 원인/스택이 노출되지 않는다."""
    from app.domains.events import service as event_service

    def boom():
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(event_service, "list_categories", boom)
    # TESTING=True면 Flask가 예외를 다시 던질 수 있어 핸들러 경로를 타도록 끈다.
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    resp = client.get("/api/events/categories")
    body = assert_envelope(resp, 500, "COMMON_INTERNAL_ERROR")
    assert body["message"] == ErrorCode.COMMON_INTERNAL_ERROR.message
    text = resp.get_data(as_text=True)
    assert "secret-internal-detail" not in text
    assert "Traceback" not in text and "RuntimeError" not in text
    assert set(body) == {"success", "code", "message"}


@pytest.mark.parametrize("member", list(ErrorCode))
def test_all_error_codes_are_upper_snake(member):
    """모든 ErrorCode 이름이 UPPER_SNAKE이고 상태 코드가 4xx/5xx다."""
    assert UPPER_SNAKE.match(member.code)
    assert 400 <= member.status_code < 600
