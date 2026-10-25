"""Review 모델/DB 제약 테스트."""
import time
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.extensions import db
from app.domains.reviews.models import Review


@pytest.mark.parametrize("rating", [0.3, 5.5, 0, 0.25])
def test_check_constraint_rejects_invalid(user, event, rating):
    db.session.add(Review(user_id=user.id, event_id=event.id, rating=rating, content="x"))
    with pytest.raises((IntegrityError, DBAPIError)):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize("rating", [0.5, 1.0, 4.5, 5.0])
def test_check_constraint_accepts_valid(make_review, user, event, rating):
    r = make_review(user, event, rating=rating)
    db.session.expire_all()
    assert db.session.get(Review, r.id).rating == Decimal(str(rating)).quantize(Decimal("0.1"))


def test_rating_numeric_roundtrip_type(make_review, user, event):
    r = make_review(user, event, rating=4.5)
    db.session.expire_all()
    assert isinstance(db.session.get(Review, r.id).rating, Decimal)


def test_fk_user_enforced(event):
    db.session.add(Review(user_id=9999, event_id=event.id, rating=3, content="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_fk_event_enforced(user):
    db.session.add(Review(user_id=user.id, event_id=9999, rating=3, content="x"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_content_not_null(user, event):
    db.session.add(Review(user_id=user.id, event_id=event.id, rating=3))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_timestamps_autofill(make_review, user, event):
    r = make_review(user, event)
    assert isinstance(r.created_at, datetime) and isinstance(r.updated_at, datetime)
    assert r.created_at == r.updated_at


def test_updated_at_changes_on_update(make_review, user, event):
    r = make_review(user, event, created_at=datetime(2020, 1, 1), updated_at=datetime(2020, 1, 1))
    r.content = "changed"
    db.session.commit()
    assert r.updated_at > datetime(2020, 1, 1)
    assert r.created_at == datetime(2020, 1, 1)
