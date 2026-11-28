"""retag_events: 저장된 행사의 태그를 사전 규칙으로 다시 계산한다."""
from datetime import date

from sqlalchemy import select

from app.core.extensions import db
from app.domains.events.models import Category, Event, Sido, Tag
from app.domains.tour.retag import retag_events


def make_event(content_id, title, description, old_tags=()):
    category = db.session.scalar(select(Category))
    sido = db.session.scalar(select(Sido))
    event = Event(
        tour_content_id=content_id, category_id=category.id, sido_code=sido.code, title=title,
        description=description, start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
    )
    event.tags = [db.session.scalar(select(Tag).where(Tag.name == name)) for name in old_tags]
    db.session.add(event)
    db.session.commit()
    return event.id


def tag_names(event_id):
    db.session.expire_all()
    return sorted(tag.name for tag in db.session.get(Event, event_id).tags)


def test_dry_run_reports_changes_without_saving(seeded):
    event_id = make_event("1", "한강 축제", "한강 불꽃축제가 열린다.", old_tags=["꽃"])

    changes = retag_events(db.session, apply=False)

    assert changes == [{"id": event_id, "title": "한강 축제", "old": ["꽃"], "new": ["불꽃놀이"]}]
    assert tag_names(event_id) == ["꽃"]


def test_apply_replaces_old_tags_with_new_rule(seeded):
    event_id = make_event("1", "한강 축제", "한강 불꽃축제가 열린다.", old_tags=["꽃"])

    retag_events(db.session, apply=True)
    db.session.commit()

    assert tag_names(event_id) == ["불꽃놀이"]


def test_unchanged_event_is_not_listed(seeded):
    make_event("1", "봄꽃 축제", "봄꽃 구경", old_tags=["꽃"])
    assert retag_events(db.session, apply=True) == []


def test_kopis_events_are_retagged_too(seeded):
    event_id = make_event("KOPIS-PF1", "음악 콘서트", "음악 음악", old_tags=[])
    retag_events(db.session, apply=True)
    db.session.commit()
    assert tag_names(event_id) == ["음악"]
