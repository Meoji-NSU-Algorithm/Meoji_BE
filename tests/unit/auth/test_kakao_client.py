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


@pytest.mark.parametrize("status", [400, 401, 500])
def test_access_token_non_200_failed(app_ctx, monkeypatch, status):
    """200이 아닌 응답은 KAKAO_TOKEN_REQUEST_FAILED이다."""
    monkeypatch.setattr(kakao_client.requests, "post", MagicMock(return_value=_resp(status=status, json_body={})))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_access_token("CODE")
    assert e.value.error_code == ErrorCode.KAKAO_TOKEN_REQUEST_FAILED


@pytest.mark.parametrize("kwargs", [
    {"json_exc": ValueError("bad json")},
    {"json_body": {}},
    {"json_body": {"other": 1}},
    {"json_body": ["access_token"]},
    {"json_body": None},
])
def test_access_token_bad_body_failed(app_ctx, monkeypatch, kwargs):
    """JSON이 아니거나 access_token이 없으면 KAKAO_TOKEN_REQUEST_FAILED이다."""
    monkeypatch.setattr(kakao_client.requests, "post", MagicMock(return_value=_resp(**kwargs)))
    with pytest.raises(BusinessException) as e:
        kakao_client.get_kakao_access_token("CODE")
    assert e.value.error_code == ErrorCode.KAKAO_TOKEN_REQUEST_FAILED


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
