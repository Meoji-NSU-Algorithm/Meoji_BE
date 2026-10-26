"""events 단위 테스트용 팩토리 픽스처. 기준 데이터는 시드되지 않으므로 직접 만든다."""
import itertools
from datetime import date, datetime, timedelta

import pytest

from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Category, Event, EventDailyView, EventTag, Sido, Tag

TODAY = date(2026, 6, 15)


def real_today():
    """list_events는 today 주입을 지원하지 않아 실제 KST 오늘을 기준으로 한다."""
    return datetime.now(KST).date()


@pytest.fixture()
def seq():
    return itertools.count(1)


@pytest.fixture()
def make_category(app_ctx, seq):
    def _make(name=None, sort_order=0):
        obj = Category(name=name or f"cat{next(seq)}", sort_order=sort_order)
        db.session.add(obj)
        db.session.commit()
        return obj
    return _make


@pytest.fixture()
def make_sido(app_ctx, seq):
    def _make(code=None, name=None, short_name=None, sort_order=0):
        n = next(seq)
        code = code or f"{n:02d}"
        obj = Sido(code=code, name=name or f"시도{code}", short_name=short_name or f"s{code}",
                   sort_order=sort_order)
        db.session.add(obj)
        db.session.commit()
        return obj
    return _make


@pytest.fixture()
def make_tag(app_ctx, seq):
    def _make(name=None):
        obj = Tag(name=name or f"tag{next(seq)}")
        db.session.add(obj)
        db.session.commit()
        return obj
    return _make


@pytest.fixture()
def base_refs(make_category, make_sido):
    return make_category("축제", 1), make_sido("44", "충청남도", "충남", 1)


@pytest.fixture()
def make_event(app_ctx, seq, base_refs):
    default_cat, default_sido = base_refs

    def _make(category=None, sido=None, title=None, start_date=None, end_date=None,
              tags=(), **kw):
        n = next(seq)
        today = real_today()
        obj = Event(
            tour_content_id=f"tc{n}",
            category_id=(category or default_cat).id,
            sido_code=(sido or default_sido).code,
            title=title or f"행사{n}",
            start_date=start_date or today - timedelta(days=1),
            end_date=end_date or today + timedelta(days=10),
            **kw,
        )
        db.session.add(obj)
        db.session.flush()
        for t in tags:
            db.session.add(EventTag(event_id=obj.id, tag_id=t.id))
        db.session.commit()
        return obj
    return _make


@pytest.fixture()
def make_daily_view(app_ctx):
    def _make(event, view_date, count):
        obj = EventDailyView(event_id=event.id, view_date=view_date, view_count=count)
        db.session.add(obj)
        db.session.commit()
        return obj
    return _make
