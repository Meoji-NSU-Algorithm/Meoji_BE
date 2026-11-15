"""bookmarks 단위 테스트용 팩토리 픽스처. 기준 데이터는 시드되지 않으므로 직접 만든다."""
import itertools
from datetime import timedelta

import pytest

from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Category, Event, Sido
from app.domains.users.models import User
from datetime import datetime


@pytest.fixture()
def seq():
    return itertools.count(1)


@pytest.fixture()
def make_user(app_ctx, seq):
    """회원을 만드는 팩토리. 반환값은 User."""

    def _make(**kw):
        n = next(seq)
        user = User(
            kakao_id=kw.pop("kakao_id", 1000 + n),
            email=kw.pop("email", f"user{n}@test.com"),
            nickname=kw.pop("nickname", f"user{n}"),
            **kw,
        )
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def make_event(app_ctx, seq):
    """행사를 만드는 팩토리. 카테고리·시도 기준 데이터는 처음 호출할 때 한 번만 만든다."""
    refs = {}

    def _make(title=None, **kw):
        if not refs:
            refs["category"] = Category(name="축제", sort_order=1)
            refs["sido"] = Sido(code="44", name="충청남도", short_name="충남", sort_order=1)
            db.session.add_all(refs.values())
            db.session.commit()
        n = next(seq)
        today = datetime.now(KST).date()
        event = Event(
            tour_content_id=f"tc{n}",
            category_id=refs["category"].id,
            sido_code=refs["sido"].code,
            title=title or f"행사{n}",
            start_date=kw.pop("start_date", today - timedelta(days=1)),
            end_date=kw.pop("end_date", today + timedelta(days=10)),
            **kw,
        )
        db.session.add(event)
        db.session.commit()
        return event

    return _make
