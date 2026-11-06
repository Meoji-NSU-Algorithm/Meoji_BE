"""길찾기 단위 테스트 공통 픽스처. 외부 API(requests.get)는 모두 가짜로 바꾼다."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from app.core.time import KST

DEPARTURE = datetime(2026, 11, 6, 12, 0, tzinfo=KST)


@pytest.fixture()
def ctx(app):
    """current_app.config를 읽는 서비스 함수를 위해 앱 컨텍스트만 연다(DB는 쓰지 않는다)."""
    with app.app_context():
        yield app


@pytest.fixture()
def keys(ctx, monkeypatch):
    """두 API 키가 모두 설정된 상태."""
    monkeypatch.setitem(ctx.config, "KAKAO_CLIENT_ID", "kakao-test-key")
    monkeypatch.setitem(ctx.config, "ODSAY_API_KEY", "odsay-test-key")
    return ctx.config


@pytest.fixture()
def event():
    """도착지 좌표만 가진 가짜 행사."""
    return SimpleNamespace(id=7, latitude=Decimal("36.8190000"), longitude=Decimal("127.1540000"))


@pytest.fixture()
def departure():
    return DEPARTURE


@pytest.fixture()
def fake_get(monkeypatch):
    """requests.get을 가짜로 바꾸고 호출 기록(list)을 돌려주는 설치 함수.

    payload는 response.json()의 반환값, status가 400 이상이면 raise_for_status가 HTTPError,
    exc를 주면 requests.get 자체가 그 예외를 던진다.
    """

    def install(payload=None, status=200, exc=None, json_error=None):
        calls = []

        def _get(url, **kwargs):
            calls.append({"url": url, **kwargs})
            if exc is not None:
                raise exc
            response = MagicMock()
            if status >= 400:
                response.raise_for_status.side_effect = requests.exceptions.HTTPError(str(status))
            else:
                response.raise_for_status.return_value = None
            if json_error is not None:
                response.json.side_effect = json_error
            else:
                response.json.return_value = payload
            return response

        monkeypatch.setattr(requests, "get", _get)
        return calls

    return install
