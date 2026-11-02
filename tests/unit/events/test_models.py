"""events 모델의 제약조건(unique/PK/FK/CHECK/cascade) 테스트."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.extensions import db
from app.domains.events.models import Category, Event, EventDailyView, EventTag, Sido, Tag


def test_category_name_unique(make_category):
    make_category("축제")
    db.session.add(Category(name="축제"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_tag_name_unique(make_tag):
    make_tag("a")
    db.session.add(Tag(name="a"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_tour_content_id_unique(make_event):
    ev = make_event()
    db.session.add(Event(tour_content_id=ev.tour_content_id, category_id=ev.category_id,
                         sido_code=ev.sido_code, title="dup",
                         start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_event_fk_category_sido(base_refs):
    cat, sido = base_refs
    db.session.add(Event(tour_content_id="x", category_id=9999, sido_code=sido.code, title="t",
                         start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(Event(tour_content_id="y", category_id=cat.id, sido_code="99", title="t",
                         start_date=date(2026, 1, 1), end_date=date(2026, 1, 2)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_event_date_check(base_refs):
    cat, sido = base_refs
    db.session.add(Event(tour_content_id="z", category_id=cat.id, sido_code=sido.code, title="t",
                         start_date=date(2026, 2, 1), end_date=date(2026, 1, 1)))
    with pytest.raises((IntegrityError, OperationalError)):  # MySQL은 CHECK 위반을 3819 OperationalError로 낸다
        db.session.commit()
    db.session.rollback()


def test_event_defaults(make_event):
    ev = make_event()
    db.session.refresh(ev)
    assert ev.view_count == 0 and ev.is_permanent is False
    assert ev.created_at is not None and ev.updated_at is not None
    assert ev.is_free is None


def test_event_tag_composite_pk(make_event, make_tag):
    tg = make_tag()
    ev = make_event(tags=[tg])
    db.session.add(EventTag(event_id=ev.id, tag_id=tg.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_event_tag_fk(make_event):
    ev = make_event()
    db.session.add(EventTag(event_id=ev.id, tag_id=99999))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_event_tag_relationship(make_event, make_tag):
    t1, t2 = make_tag("a"), make_tag("b")
    ev = make_event(tags=[t1, t2])
    db.session.expire_all()
    assert {t.name for t in db.session.get(Event, ev.id).tags} == {"a", "b"}
    assert [e.id for e in db.session.get(Tag, t1.id).events] == [ev.id]


def test_daily_view_unique_per_event_date(make_event, make_daily_view):
    ev = make_event()
    make_daily_view(ev, date(2026, 6, 1), 1)
    db.session.add(EventDailyView(event_id=ev.id, view_date=date(2026, 6, 1), view_count=5))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    make_daily_view(ev, date(2026, 6, 2), 1)  # 다른 날짜는 가능


def test_daily_view_fk(app_ctx):
    db.session.add(EventDailyView(event_id=9999, view_date=date(2026, 6, 1), view_count=1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_event_delete_cascades(make_event, make_tag, make_daily_view):
    tg = make_tag()
    ev = make_event(tags=[tg])
    make_daily_view(ev, date(2026, 6, 1), 1)
    eid = ev.id
    db.session.delete(ev)
    db.session.commit()
    assert db.session.query(EventTag).filter_by(event_id=eid).count() == 0
    assert db.session.query(EventDailyView).filter_by(event_id=eid).count() == 0
    assert db.session.get(Tag, tg.id) is not None


def test_delete_category_in_use_blocked(make_event, base_refs):
    make_event()
    with pytest.raises(IntegrityError):
        db.session.execute(text("DELETE FROM categories"))
        db.session.commit()
    db.session.rollback()
