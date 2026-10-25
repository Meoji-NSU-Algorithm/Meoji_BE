"""리뷰 서비스 테스트."""
from datetime import datetime
from decimal import Decimal

import pytest

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.reviews import service
from app.domains.reviews.models import Review


def code_of(exc_info):
    return exc_info.value.error_code


# ---------- create ----------
def test_create_review_success(user, event):
    r = service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4.5, "content": "굿"})
    assert r.id is not None
    db.session.expire_all()
    got = db.session.get(Review, r.id)
    assert (got.user_id, got.event_id, got.content) == (user.id, event.id, "굿")
    assert got.rating == Decimal("4.5")


def test_create_review_event_not_found(user):
    with pytest.raises(BusinessException) as e:
        service.create_review({"user_id": user.id, "event_id": 9999, "rating": 4, "content": "x"})
    assert code_of(e) == ErrorCode.EVENT_NOT_FOUND


def test_create_review_user_not_found(event):
    with pytest.raises(BusinessException) as e:
        service.create_review({"user_id": 9999, "event_id": event.id, "rating": 4, "content": "x"})
    assert code_of(e) == ErrorCode.USER_NOT_FOUND


def test_create_review_both_missing_reports_user_first(event):
    with pytest.raises(BusinessException) as e:
        service.create_review({"user_id": 9999, "event_id": 9999, "rating": 4, "content": "x"})
    assert code_of(e) == ErrorCode.USER_NOT_FOUND


def test_create_duplicate_review_currently_allowed(user, event):
    # 현재 동작: 같은 사용자가 같은 행사에 여러 리뷰를 쓸 수 있다 (unique 제약/중복 검사 없음).
    d = {"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"}
    a = service.create_review(d)
    b = service.create_review(d)
    assert a.id != b.id
    assert len(service.get_reviews_by_event(event.id)) == 2


def test_create_review_rating_out_of_range_bypassing_schema_raises_db_error(user, event):
    # 서비스는 평점을 검증하지 않고 DB CHECK에 맡긴다. 이 경우 BusinessException이 아닌 DB 오류가 올라온다.
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        service.create_review({"user_id": user.id, "event_id": event.id, "rating": 7, "content": "x"})
    db.session.rollback()


# ---------- list by event ----------
def test_reviews_by_event_empty(event):
    assert service.get_reviews_by_event(event.id) == []


def test_reviews_by_event_nonexistent_returns_empty_without_check(app_ctx):
    # get_reviews_by_event 자체는 행사 존재를 확인하지 않는다.
    assert service.get_reviews_by_event(9999) == []


def test_ensure_event_exists(event):
    service.ensure_event_exists(event.id)
    with pytest.raises(BusinessException) as e:
        service.ensure_event_exists(9999)
    assert code_of(e) == ErrorCode.EVENT_NOT_FOUND


def test_reviews_by_event_ordering(make_user, event, make_event, make_review):
    u = make_user()
    other = make_event()
    t = datetime
    a = make_review(u, event, created_at=t(2026, 1, 1), updated_at=t(2026, 1, 5))
    b = make_review(u, event, created_at=t(2026, 1, 3), updated_at=t(2026, 1, 4))
    c = make_review(u, event, created_at=t(2026, 1, 2), updated_at=t(2026, 1, 4))
    d = make_review(u, event, created_at=t(2026, 1, 2), updated_at=t(2026, 1, 4))
    make_review(u, other)
    got = [r.id for r in service.get_reviews_by_event(event.id)]
    # updated_at desc: a; 동률(1/4)은 created_at desc: b; 동률은 id desc: d, c
    assert got == [a.id, b.id, d.id, c.id]


# ---------- my reviews ----------
def test_my_reviews_only_own_and_ordered(make_user, make_event, make_review):
    me, other = make_user(), make_user()
    e1, e2 = make_event(), make_event()
    t = datetime
    old = make_review(me, e1, created_at=t(2026, 1, 1), updated_at=t(2026, 1, 1))
    new = make_review(me, e2, created_at=t(2026, 1, 1), updated_at=t(2026, 2, 1))
    make_review(other, e1)
    assert [r.id for r in service.get_my_reviews(me.id)] == [new.id, old.id]


def test_my_reviews_empty(user):
    assert service.get_my_reviews(user.id) == []
    assert service.get_my_reviews(9999) == []


# ---------- rating info ----------
def test_rating_info_no_reviews(event):
    assert service.get_rating_info(event.id) == {"average_rating": 0, "review_count": 0}


def test_rating_info_nonexistent_event(app_ctx):
    assert service.get_rating_info(9999) == {"average_rating": 0, "review_count": 0}


def test_rating_info_average_and_count(make_user, event, make_review):
    for rating in (5.0, 4.5, 4.0):
        make_review(make_user(), event, rating=rating)
    info = service.get_rating_info(event.id)
    assert info == {"average_rating": 4.5, "review_count": 3}
    assert isinstance(info["average_rating"], float)


def test_rating_info_rounding_to_one_decimal(make_user, event, make_review):
    for rating in (5.0, 5.0, 4.5):  # 4.8333
        make_review(make_user(), event, rating=rating)
    assert service.get_rating_info(event.id)["average_rating"] == 4.8


def test_rating_info_single_review(user, event, make_review):
    make_review(user, event, rating=0.5)
    assert service.get_rating_info(event.id) == {"average_rating": 0.5, "review_count": 1}


def test_rating_info_other_event_not_counted(user, event, make_event, make_review):
    make_review(user, event, rating=1.0)
    make_review(user, make_event(), rating=5.0)
    assert service.get_rating_info(event.id) == {"average_rating": 1.0, "review_count": 1}


def test_rating_info_half_rounding(make_user, event, make_review):
    # 평균 3.25 -> round(3.25, 1): float 이진 표현상 3.2. 값 자체를 고정해 반올림 방식을 문서화한다.
    for rating in (3.0, 3.5, 3.0, 3.5):
        make_review(make_user(), event, rating=rating)
    assert service.get_rating_info(event.id)["average_rating"] == 3.2


# ---------- update ----------
def test_update_owner_rating_only(user, event, make_review):
    r = make_review(user, event, rating=4.0, content="old")
    out = service.update_review(r.id, user.id, {"rating": 2.5})
    db.session.expire_all()
    got = db.session.get(Review, out.id)
    assert got.rating == Decimal("2.5") and got.content == "old"


def test_update_owner_content_only(user, event, make_review):
    r = make_review(user, event, rating=4.0, content="old")
    service.update_review(r.id, user.id, {"content": "new"})
    db.session.expire_all()
    got = db.session.get(Review, r.id)
    assert got.rating == Decimal("4.0") and got.content == "new"


def test_update_bumps_updated_at(user, event, make_review):
    r = make_review(user, event, created_at=datetime(2020, 1, 1), updated_at=datetime(2020, 1, 1))
    service.update_review(r.id, user.id, {"content": "new"})
    assert r.updated_at > datetime(2020, 1, 1)


def test_update_empty_data_is_noop(user, event, make_review):
    r = make_review(user, event, content="old")
    out = service.update_review(r.id, user.id, {})
    assert out.content == "old"


def test_update_ignores_unknown_keys(user, event, make_user, make_review):
    r = make_review(user, event)
    service.update_review(r.id, user.id, {"user_id": 999, "event_id": 999, "content": "n"})
    assert r.user_id == user.id and r.event_id == event.id


def test_update_forbidden(user, event, make_user, make_review):
    r = make_review(user, event, content="old")
    other = make_user()
    with pytest.raises(BusinessException) as e:
        service.update_review(r.id, other.id, {"content": "hack"})
    assert code_of(e) == ErrorCode.REVIEW_FORBIDDEN
    db.session.expire_all()
    assert db.session.get(Review, r.id).content == "old"


def test_update_not_found(user):
    with pytest.raises(BusinessException) as e:
        service.update_review(9999, user.id, {"content": "x"})
    assert code_of(e) == ErrorCode.REVIEW_NOT_FOUND


# ---------- delete ----------
def test_delete_owner(user, event, make_review):
    r = make_review(user, event)
    rid = r.id
    out = service.delete_review(rid, user.id)
    assert out.id == rid
    db.session.expire_all()
    assert db.session.get(Review, rid) is None


def test_delete_forbidden(user, event, make_user, make_review):
    r = make_review(user, event)
    with pytest.raises(BusinessException) as e:
        service.delete_review(r.id, make_user().id)
    assert code_of(e) == ErrorCode.REVIEW_FORBIDDEN
    assert db.session.get(Review, r.id) is not None


def test_delete_not_found(user):
    with pytest.raises(BusinessException) as e:
        service.delete_review(9999, user.id)
    assert code_of(e) == ErrorCode.REVIEW_NOT_FOUND


def test_delete_twice_second_not_found(user, event, make_review):
    r = make_review(user, event)
    service.delete_review(r.id, user.id)
    with pytest.raises(BusinessException) as e:
        service.delete_review(r.id, user.id)
    assert code_of(e) == ErrorCode.REVIEW_NOT_FOUND
