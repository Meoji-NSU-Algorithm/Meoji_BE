"""directions 단위 테스트 공통 fixture. 외부 API(카카오 모빌리티, ODsay)는 절대 호출하지 않는다."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.time import KST


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """실수로 실제 HTTP 호출이 나가면 즉시 실패시킨다(ODsay는 하루 30회 제한)."""
    import requests

    def boom(*a, **kw):
        raise AssertionError("실제 외부 API 호출 금지")

    monkeypatch.setattr(requests, "get", boom)
    monkeypatch.setattr(requests.Session, "request", boom)


@pytest.fixture()
def api_keys(app, monkeypatch):
    monkeypatch.setitem(app.config, "KAKAO_CLIENT_ID", "kakao-key")
    monkeypatch.setitem(app.config, "ODSAY_API_KEY", "odsay-key")
    return app


@pytest.fixture()
def ctx(api_keys):
    """current_app 이 필요한 코드용 앱 컨텍스트."""
    with api_keys.app_context():
        yield api_keys


@pytest.fixture()
def event():
    return SimpleNamespace(id=7, latitude=Decimal("36.8"), longitude=Decimal("127.1"))


@pytest.fixture()
def departure():
    return datetime(2026, 1, 1, 9, 0, tzinfo=KST)


@pytest.fixture()
def fake_request(monkeypatch):
    """`request_json` 을 가짜로 바꾸고 호출 인자를 기록한다. payload 를 예외로 주면 raise."""

    def install(module, payload):
        calls = []

        def fake(url, params, headers=None):
            calls.append({"url": url, "params": params, "headers": headers})
            if isinstance(payload, Exception):
                raise payload
            return payload

        monkeypatch.setattr(module, "request_json", fake)
        return calls

    return install
