"""client.get_api_key / request_json. requests.get 은 전부 가짜."""
import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.directions import client


class FakeResp:
    def __init__(self, payload=None, status_err=None, json_err=None):
        self.payload, self.status_err, self.json_err = payload, status_err, json_err

    def raise_for_status(self):
        if self.status_err:
            raise self.status_err

    def json(self):
        if self.json_err:
            raise self.json_err
        return self.payload


def code_of(exc_info):
    return exc_info.value.error_code


def test_get_api_key_returns_value(ctx):
    assert client.get_api_key("KAKAO_CLIENT_ID") == "kakao-key"


@pytest.mark.parametrize("value", [None, ""])
def test_get_api_key_missing(ctx, monkeypatch, value):
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", value)
    with pytest.raises(BusinessException) as ei:
        client.get_api_key("ODSAY_API_KEY")
    assert code_of(ei) == ErrorCode.DIRECTIONS_API_KEY_MISSING


def test_request_json_success_passes_args_and_timeout(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params, headers=headers, timeout=timeout)
        return FakeResp({"ok": 1})

    monkeypatch.setattr(requests, "get", fake_get)
    assert client.request_json("http://x", {"a": 1}, {"h": "v"}) == {"ok": 1}
    assert seen == {"url": "http://x", "params": {"a": 1}, "headers": {"h": "v"}, "timeout": 10}


@pytest.mark.parametrize("exc,code", [
    (requests.Timeout(), ErrorCode.DIRECTIONS_API_TIMEOUT),
    (requests.ConnectTimeout(), ErrorCode.DIRECTIONS_API_TIMEOUT),
    (requests.ConnectionError(), ErrorCode.DIRECTIONS_API_ERROR),
    (requests.RequestException(), ErrorCode.DIRECTIONS_API_ERROR),
])
def test_request_json_transport_errors(monkeypatch, exc, code):
    def fake_get(*a, **kw):
        raise exc

    monkeypatch.setattr(requests, "get", fake_get)
    with pytest.raises(BusinessException) as ei:
        client.request_json("http://x", {})
    assert code_of(ei) == code


def test_request_json_http_error_status(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(status_err=requests.HTTPError("500")))
    with pytest.raises(BusinessException) as ei:
        client.request_json("http://x", {})
    assert code_of(ei) == ErrorCode.DIRECTIONS_API_ERROR


def test_request_json_invalid_json(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(json_err=ValueError("bad")))
    with pytest.raises(BusinessException) as ei:
        client.request_json("http://x", {})
    assert code_of(ei) == ErrorCode.DIRECTIONS_API_ERROR


@pytest.mark.parametrize("payload", [[], "str", 1, None])
def test_request_json_non_dict_body(monkeypatch, payload):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResp(payload))
    with pytest.raises(BusinessException) as ei:
        client.request_json("http://x", {})
    assert code_of(ei) == ErrorCode.DIRECTIONS_API_ERROR
