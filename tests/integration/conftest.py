"""HTTP 통합 테스트용 픽스처. 카카오 호출만 가짜로 바꾸고 나머지는 실제 앱/DB를 쓴다."""
import itertools
from datetime import timedelta

import pytest

from app.core.extensions import db
from app.core.time import KST
from app.domains.auth import kakao_client
from app.domains.events.models import Category, Event, EventTag, Sido, Tag
from datetime import datetime


@pytest.fixture()
def kakao_profiles(monkeypatch):
    """카카오 통신을 가짜로 바꾸고, code별 프로필을 등록하는 dict를 돌려준다."""
    profiles = {}

    def fake_token(code):
        return f"kakao-token-{code}"

    def fake_info(token):
        return dict(profiles[token.removeprefix("kakao-token-")])

    # auth.service는 kakao_client 모듈 속성으로 호출하므로 모듈에서 바꾸면 된다.
    monkeypatch.setattr(kakao_client, "get_kakao_access_token", fake_token)
    monkeypatch.setattr(kakao_client, "get_kakao_user_info", fake_info)
    return profiles


@pytest.fixture()
def login(client, kakao_profiles):
    """실제 로그인 API로 가입/로그인하고 (헤더, 토큰, user_id)를 돌려주는 함수."""

    def _login(kakao_id=1001, email=None, nickname=None):
        code = f"code-{kakao_id}-{len(kakao_profiles)}"
        kakao_profiles[code] = {
            "kakao_id": kakao_id,
            "email": email or f"user{kakao_id}@test.com",
            "nickname": nickname or f"user{kakao_id}",
            "profile_image": None,
        }
        resp = client.post("/api/auth/kakao", json={"code": code})
        assert resp.status_code == 200, resp.get_json()
        tokens = resp.get_json()["data"]
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me = client.get("/api/users/me", headers=headers).get_json()["data"]
        return headers, tokens, me["id"]

    return _login


@pytest.fixture()
def bearer():
    """토큰 문자열로 Authorization 헤더를 만드는 함수."""
    return lambda token: {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def seq():
    return itertools.count(1)


@pytest.fixture()
def refs(app_ctx):
    """기준 데이터(카테고리 2개, 시도 2개)를 만든다."""
    cats = [Category(name="축제", sort_order=1), Category(name="공연", sort_order=2)]
    sidos = [Sido(code="44", name="충청남도", short_name="충남", sort_order=1),
             Sido(code="11", name="서울특별시", short_name="서울", sort_order=2)]
    db.session.add_all(cats + sidos)
    db.session.commit()
    return {"cats": cats, "sidos": sidos}


@pytest.fixture()
def make_tag(app_ctx, seq):
    def _make(name=None):
        tag = Tag(name=name or f"tag{next(seq)}")
        db.session.add(tag)
        db.session.commit()
        return tag
    return _make


@pytest.fixture()
def make_event(app_ctx, seq, refs):
    """종료되지 않은 행사를 만드는 팩토리. 반환값은 Event."""

    def _make(category=None, sido=None, title=None, tags=(), **kw):
        n = next(seq)
        today = datetime.now(KST).date()
        event = Event(
            tour_content_id=f"tc{n}",
            category_id=(category or refs["cats"][0]).id,
            sido_code=(sido or refs["sidos"][0]).code,
            title=title or f"행사{n}",
            start_date=kw.pop("start_date", today - timedelta(days=1)),
            end_date=kw.pop("end_date", today + timedelta(days=10)),
            **kw,
        )
        db.session.add(event)
        db.session.flush()
        for tag in tags:
            db.session.add(EventTag(event_id=event.id, tag_id=tag.id))
        db.session.commit()
        return event

    return _make
