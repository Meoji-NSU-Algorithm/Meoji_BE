"""리뷰 테스트용 팩토리 픽스처."""
import itertools
from datetime import date, datetime

import pytest

from app.core.extensions import db
from app.domains.events.models import Category, Event, Sido
from app.domains.reviews.models import Review
from app.domains.users.models import User


@pytest.fixture()
def make_user(app_ctx):
    counter = itertools.count(1)

    def _make(**kw):
        n = next(counter)
        user = User(kakao_id=kw.pop("kakao_id", 1000 + n), email=kw.pop("email", f"u{n}@test.com"),
                    nickname=kw.pop("nickname", f"user{n}"), **kw)
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def make_event(app_ctx):
    counter = itertools.count(1)

    def _make(**kw):
        n = next(counter)
        category = db.session.get(Category, 1)
        if category is None:
            category = Category(id=1, name="축제", sort_order=1)
            db.session.add(category)
        if db.session.get(Sido, "34") is None:
            db.session.add(Sido(code="34", name="충청남도", short_name="충남", sort_order=1))
        db.session.flush()
        event = Event(tour_content_id=kw.pop("tour_content_id", f"T{n}"), category_id=1, sido_code="34",
                      title=kw.pop("title", f"event{n}"), start_date=date(2026, 1, 1),
                      end_date=date(2026, 1, 2), **kw)
        db.session.add(event)
        db.session.commit()
        return event

    return _make


@pytest.fixture()
def make_review(app_ctx):
    def _make(user, event, rating=4.0, content="좋아요", created_at=None, updated_at=None):
        review = Review(user_id=user.id, event_id=event.id, rating=rating, content=content)
        if created_at:
            review.created_at = created_at
        if updated_at:
            review.updated_at = updated_at
        db.session.add(review)
        db.session.commit()
        return review

    return _make


@pytest.fixture()
def user(make_user):
    return make_user()


@pytest.fixture()
def event(make_event):
    return make_event()
