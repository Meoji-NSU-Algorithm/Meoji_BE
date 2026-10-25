"""kakao_client 단위 테스트. requests를 mock하여 네트워크 없이 검증한다."""
from unittest.mock import MagicMock

import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.auth import kakao_client


def _resp(status=200, json_body=None, json_exc=None, text="body"):
    r = MagicMock()
    r.status_code = status
    r.text = text
    if json_exc:
        r.json.side_effect = json_exc
    else:
        r.json.return_value = json_body
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError("err")
    return r


# ---------- get_kakao_access_token ----------

def test_access_token_success(app_ctx, monkeypatch):
    """정상 응답이면 access_token 문자열을 반환한다."""
    post = MagicMock(return_value=_resp(json_body={"access_token": "tok"}))
    monkeypatch.setattr(kakao_client.requests, "post", post)
    assert kakao_client.get_kakao_access_token("CODE") == "tok"


def test_access_token_request_params(app_ctx, monkeypatch):
    """form data, URL, timeout이 올바르게 전달되고 secret이 None이면 생략된다."""
    post = MagicMock(return_value=_resp(json_body={"access_token": "tok"}))
    monkeypatch.setattr(kakao_client.requests, "post", post)
    kakao_client.get_kakao_access_token("CODE")
    args, kwargs = post.call_args
    assert args[0] == kakao_client.KAKAO_TOKEN_URL
    assert kwargs["timeout"] == kakao_client.TIMEOUT
    assert "json" not in kwargs
    assert kwargs["data"] == {
        "grant_type": "authorization_code",
        "client_id": "test-kakao-client",
        "redirect_uri": "http://localhost/callback",
        "code": "CODE",
    }
    assert "client_secret" not in kwargs["data"]


def test_access_token_includes_client_secret_when_set(app_ctx, monkeypatch):
    """KAKAO_CLIENT_SECRET이 설정되면 data에 client_secret이 포함된다."""
    app_ctx.config["KAKAO_CLIENT_SECRET"] = "shh"
    try:
        post = MagicMock(return_value=_resp(json_body={"access_token": "tok"}))
        monkeypatch.setattr(kakao_client.requests, "post", post)
        kakao_client.get_kakao_access_token("CODE")
        assert post.call_args.kwargs["data"]["client_secret"] == "shh"
    finally:
        app_ctx.config["KAKAO_CLIENT_SECRET"] = None


@pytest.mark.parametrize("exc", [requests.Timeout(), requests.ConnectionError()])
def test_access_token_network_error_unavailable(app_ctx, monkeypatch, exc):
    """타임아웃/연결 오류는 KAKAO_API_UNAVAILABLE로 변환된다."""
    monkeypatch.setattr(kakao_client.requests, "post", MagicMock(side_effect=exc))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_access_token("CODE")
    assert e.value.error_code == ErrorCode.KAKAO_API_UNAVAILABLE


def _call_expecting(monkeypatch, **resp_kwargs):
    monkeypatch.setattr(kakao_client.requests, "post", MagicMock(return_value=_resp(**resp_kwargs)))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_access_token("CODE")
    return e.value.error_code


@pytest.mark.parametrize("status,body", [
    (400, {"error": "invalid_grant", "error_code": "KOE320"}),
    (400, {"error": "invalid_request", "error_code": "KOE303"}),
    (401, {"error": "invalid_grant"}),
    (403, {}),
    (400, {"error": ["unexpected-type"]}),
])
def test_access_token_client_4xx_failed(app_ctx, monkeypatch, status, body):
    """code 문제로 보이는 4xx는 KAKAO_TOKEN_REQUEST_FAILED(401)이다."""
    assert _call_expecting(monkeypatch, status=status, json_body=body) == ErrorCode.KAKAO_TOKEN_REQUEST_FAILED


@pytest.mark.parametrize("status", [500, 502, 503, 429])
def test_access_token_5xx_and_429_unavailable(app_ctx, monkeypatch, status):
    """5xx와 429는 KAKAO_API_UNAVAILABLE이다."""
    assert _call_expecting(monkeypatch, status=status, json_body={"error": "x"}) == ErrorCode.KAKAO_API_UNAVAILABLE


@pytest.mark.parametrize("status", [400, 401, 403])
def test_access_token_non_json_error_body_unavailable(app_ctx, monkeypatch, status):
    """JSON이 아닌 오류 본문은 KAKAO_API_UNAVAILABLE이다."""
    code = _call_expecting(monkeypatch, status=status, json_exc=ValueError("no json"), text="<html>")
    assert code == ErrorCode.KAKAO_API_UNAVAILABLE


@pytest.mark.parametrize("body", [
    {"error": "invalid_client"},
    {"error": "unauthorized_client"},
    {"error": "invalid_request", "error_code": "KOE010"},
    {"error": "invalid_request", "error_code": "KOE101"},
])
def test_access_token_server_config_error_unavailable_and_logged(app_ctx, monkeypatch, caplog, body):
    """서버의 카카오 설정 오류는 502이며 ERROR 로그에 원문 body 없이 필드만 남는다."""
    body = {**body, "error_description": "bad client", "secret_like": "SHOULD-NOT-LEAK"}
    with caplog.at_level("ERROR"):
        code = _call_expecting(monkeypatch, status=401, json_body=body)
    assert code == ErrorCode.KAKAO_API_UNAVAILABLE
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert errors
    assert "bad client" in errors[0].getMessage()
    assert "SHOULD-NOT-LEAK" not in caplog.text


def test_access_token_4xx_log_truncated_and_no_raw_body(app_ctx, monkeypatch, caplog):
    """4xx 경고 로그는 필드를 200자로 자르고 원문 body를 남기지 않는다."""
    body = {"error": "invalid_grant", "error_description": "d" * 500, "extra": "RAW-LEAK"}
    with caplog.at_level("WARNING"):
        _call_expecting(monkeypatch, status=400, json_body=body)
    assert "d" * 200 in caplog.text
    assert "d" * 201 not in caplog.text
    assert "RAW-LEAK" not in caplog.text


@pytest.mark.parametrize("kwargs", [
    {"json_exc": ValueError("bad json")},
    {"json_body": {}},
    {"json_body": {"other": 1}},
    {"json_body": ["access_token"]},
    {"json_body": None},
    {"json_body": {"access_token": ""}},
    {"json_body": {"access_token": 123}},
    {"json_body": {"access_token": None}},
])
def test_access_token_bad_200_body_unavailable(app_ctx, monkeypatch, kwargs):
    """200이어도 access_token이 비어 있거나 JSON이 아니면 KAKAO_API_UNAVAILABLE이다."""
    assert _call_expecting(monkeypatch, status=200, **kwargs) == ErrorCode.KAKAO_API_UNAVAILABLE


# ---------- get_kakao_user_info ----------

def _profile_body(**over):
    body = {"id": 123, "kakao_account": {"email": "a@b.com", "profile": {"nickname": "nick", "profile_image_url": "http://img"}}}
    body.update(over)
    return body


def test_user_info_success(app_ctx, monkeypatch):
    """정상 응답을 User 필드명으로 변환하고 Bearer 헤더/timeout을 보낸다."""
    get = MagicMock(return_value=_resp(json_body=_profile_body()))
    monkeypatch.setattr(kakao_client.requests, "get", get)
    info = kakao_client.get_kakao_user_info("KT")
    assert info == {"kakao_id": 123, "email": "a@b.com", "nickname": "nick", "profile_image": "http://img"}
    args, kwargs = get.call_args
    assert args[0] == kakao_client.KAKAO_USER_INFO_URL
    assert kwargs["headers"] == {"Authorization": "Bearer KT"}
    assert kwargs["timeout"] == kakao_client.TIMEOUT


def test_user_info_profile_image_optional(app_ctx, monkeypatch):
    """profile_image_url이 없으면 profile_image는 None이다."""
    body = _profile_body()
    del body["kakao_account"]["profile"]["profile_image_url"]
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(json_body=body)))
    assert kakao_client.get_kakao_user_info("KT")["profile_image"] is None


@pytest.mark.parametrize("exc", [requests.Timeout(), requests.ConnectionError()])
def test_user_info_network_error_unavailable(app_ctx, monkeypatch, exc):
    """통신 오류는 KAKAO_API_UNAVAILABLE이다."""
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(side_effect=exc))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_user_info("KT")
    assert e.value.error_code == ErrorCode.KAKAO_API_UNAVAILABLE


def test_user_info_http_error_unavailable(app_ctx, monkeypatch):
    """4xx/5xx 응답은 KAKAO_API_UNAVAILABLE이다."""
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(status=401, json_body={})))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_user_info("KT")
    assert e.value.error_code == ErrorCode.KAKAO_API_UNAVAILABLE


def test_user_info_invalid_json_unavailable(app_ctx, monkeypatch):
    """JSON이 아닌 응답은 KAKAO_API_UNAVAILABLE이다."""
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(json_exc=ValueError())))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_user_info("KT")
    assert e.value.error_code == ErrorCode.KAKAO_API_UNAVAILABLE


@pytest.mark.parametrize("body", [
    {"id": 1},
    {"id": 1, "kakao_account": {}},
    {"id": 1, "kakao_account": {"email": "a@b.com"}},
    {"id": 1, "kakao_account": {"profile": {"nickname": "n"}}},
    {"id": 1, "kakao_account": {"email": "a@b.com", "profile": {}}},
    {"kakao_account": {"email": "a@b.com", "profile": {"nickname": "n"}}},
    {"id": 1, "kakao_account": None},
    {"id": 1, "kakao_account": {"email": "a@b.com", "profile": None}},
])
def test_user_info_missing_required_profile_invalid(app_ctx, monkeypatch, body):
    """kakao_account/email/profile/nickname/id 누락은 KAKAO_PROFILE_INVALID이다."""
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(json_body=body)))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_user_info("KT")
    assert e.value.error_code == ErrorCode.KAKAO_PROFILE_INVALID


def test_user_info_body_not_dict_profile_invalid(app_ctx, monkeypatch):
    """응답 JSON이 리스트여도 500이 아니라 KAKAO_PROFILE_INVALID로 처리된다."""
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(json_body=[1, 2])))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_user_info("KT")
    assert e.value.error_code == ErrorCode.KAKAO_PROFILE_INVALID


def test_user_info_profile_not_dict_does_not_crash(app_ctx, monkeypatch):
    """profile이 문자열 등 비정상 타입이어도 BusinessException으로 처리된다."""
    body = {"id": 1, "kakao_account": {"email": "a@b.com", "profile": "x"}}
    monkeypatch.setattr(kakao_client.requests, "get", MagicMock(return_value=_resp(json_body=body)))
    with pytest.raises(BusinessException):
        kakao_client.get_kakao_user_info("KT")
