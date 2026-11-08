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


def test_create_duplicate_review_rejected(user, event):
    d = {"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"}
    service.create_review(d)
    with pytest.raises(BusinessException) as e:
        service.create_review(d)
    assert code_of(e) == ErrorCode.REVIEW_ALREADY_EXISTS
    assert len(service.get_reviews_by_event(event.id)) == 1


def test_create_same_user_different_event_ok(user, event, make_event):
    other = make_event()
    service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"})
    service.create_review({"user_id": user.id, "event_id": other.id, "rating": 4, "content": "x"})
    assert len(service.get_my_reviews(user.id)["reviews"]) == 2


def test_create_different_user_same_event_ok(user, event, make_user):
    other = make_user()
    service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"})
    service.create_review({"user_id": other.id, "event_id": event.id, "rating": 5, "content": "y"})
    assert len(service.get_reviews_by_event(event.id)) == 2


def test_update_own_review_unaffected_by_unique(user, event):
    r = service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"})
    updated = service.update_review(r.id, user.id, {"rating": 5, "content": "수정"})
    assert updated.content == "수정"


def test_create_race_maps_unique_violation_and_session_usable(user, event, make_event, monkeypatch):
    """사전 조회를 통과한 뒤 경쟁 요청이 먼저 확정되면 REVIEW_ALREADY_EXISTS로 변환한다."""
    from sqlalchemy import text
    real_commit = db.session.commit

    def racing_commit():
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO review (user_id, event_id, rating, content, created_at, updated_at) "
                "VALUES (:u, :e, 3.0, 'rival', NOW(), NOW())"), {"u": user.id, "e": event.id})
        return real_commit()

    monkeypatch.setattr(db.session, "commit", racing_commit)
    with pytest.raises(BusinessException) as e:
        service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"})
    assert code_of(e) == ErrorCode.REVIEW_ALREADY_EXISTS
    monkeypatch.undo()

    # 롤백 후 세션이 계속 사용 가능해야 한다.
    other = make_event()
    service.create_review({"user_id": user.id, "event_id": other.id, "rating": 4, "content": "x"})
    assert len(service.get_reviews_by_event(event.id)) == 1


def test_create_non_duplicate_integrity_error_reraised(user, event, monkeypatch):
    """unique 위반(1062)이 아닌 IntegrityError는 그대로 올리고 세션은 롤백한다."""
    from sqlalchemy.exc import IntegrityError

    def boom():
        raise IntegrityError("stmt", {}, Exception(1452, "fk fail"))

    monkeypatch.setattr(db.session, "commit", boom)
    with pytest.raises(IntegrityError):
        service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x"})


def test_create_review_rating_out_of_range_bypassing_schema_raises_db_error(user, event):
    # 서비스는 평점을 검증하지 않고 DB CHECK에 맡긴다. 이 경우 BusinessException이 아닌 DB 오류가 올라온다.
    from sqlalchemy.exc import DBAPIError
    with pytest.raises(DBAPIError):
        service.create_review({"user_id": user.id, "event_id": event.id, "rating": 7, "content": "x"})
    db.session.rollback()


# ---------- list by event ----------
def test_reviews_by_event_empty(event):
    assert service.get_reviews_by_event(event.id) == []


def test_reviews_by_event_nonexistent_returns_empty(app_ctx):
    # 행사가 없어도 오류 없이 빈 목록을 반환한다.
    assert service.get_reviews_by_event(9999) == []


def test_reviews_by_event_ordering(make_user, event, make_event, make_review):
    # 사용자당 행사별 리뷰는 하나뿐이므로 리뷰마다 다른 사용자를 쓴다.
    u1, u2, u3, u4 = make_user(), make_user(), make_user(), make_user()
    other = make_event()
    t = datetime
    a = make_review(u1, event, created_at=t(2026, 1, 1), updated_at=t(2026, 1, 5))
    b = make_review(u2, event, created_at=t(2026, 1, 3), updated_at=t(2026, 1, 4))
    c = make_review(u3, event, created_at=t(2026, 1, 2), updated_at=t(2026, 1, 4))
    d = make_review(u4, event, created_at=t(2026, 1, 2), updated_at=t(2026, 1, 4))
    make_review(u1, other)
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
    result = service.get_my_reviews(me.id)

    assert result["total_count"] == 2
    assert [r["id"] for r in result["reviews"]] == [new.id, old.id]


def test_my_reviews_empty(user):
    assert service.get_my_reviews(user.id) == {
        "total_count": 0,
        "page": 1,
        "size": 20,
        "reviews": [],
    }

    assert service.get_my_reviews(9999) == {
        "total_count": 0,
        "page": 1,
        "size": 20,
        "reviews": [],
    }


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


def test_create_race_with_images_maps_to_already_exists(user, event, monkeypatch):
    """이슈 #35: 사진이 있는 리뷰도 동시 중복 제출이면 500이 아니라 REVIEW_ALREADY_EXISTS다."""
    from sqlalchemy import text
    from app.domains.reviews.models import ReviewImageUpload

    key = "reviews/" + "c" * 32 + ".webp"
    db.session.add(ReviewImageUpload(key=key, user_id=user.id))
    db.session.commit()
    real_check = service._ensure_images_not_attached

    def racing_check(keys, review_id=None):
        # 중복 조회를 통과한 직후 경쟁 요청의 리뷰가 먼저 확정된 상황
        with db.engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO review (user_id, event_id, rating, content, created_at, updated_at) "
                "VALUES (:u, :e, 3.0, 'rival', NOW(), NOW())"), {"u": user.id, "e": event.id})
        real_check(keys, review_id)

    monkeypatch.setattr(service, "_ensure_images_not_attached", racing_check)
    with pytest.raises(BusinessException) as e:
        service.create_review({"user_id": user.id, "event_id": event.id, "rating": 4, "content": "x", "images": [key]})
    assert code_of(e) == ErrorCode.REVIEW_ALREADY_EXISTS
    # 롤백으로 업로드 기록이 되살아나 다시 첨부할 수 있다
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is not None


# ---------- 점검 보고서 L3·L4: 수정·삭제 경합 ----------
def test_update_after_concurrent_delete_is_not_found(user, event, make_review):
    """다른 요청이 먼저 삭제를 커밋했으면 수정은 500(StaleDataError)이 아니라 REVIEW_NOT_FOUND다."""
    from sqlalchemy import text

    review = make_review(user, event)
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM review WHERE id = :id"), {"id": review.id})

    with pytest.raises(BusinessException) as e:
        service.update_review(review.id, user.id, {"content": "수정"})
    assert code_of(e) == ErrorCode.REVIEW_NOT_FOUND


def test_update_reads_images_committed_by_concurrent_update(user, event, make_review, monkeypatch):
    """세션에 남은 옛 images가 아니라 잠금 뒤 최신 images와 비교해, 앞 수정이 붙인 사진도 정리 대상에 넣는다."""
    from sqlalchemy import text

    review = make_review(user, event)
    review.images  # 세션에 images=None 상태를 올려 둔다
    key = "reviews/" + "c" * 32 + ".webp"
    with db.engine.begin() as conn:
        conn.execute(text("UPDATE review SET images = :images WHERE id = :id"),
                     {"images": f'["{key}"]', "id": review.id})

    removed = []
    monkeypatch.setattr(service, "_delete_unreferenced_images", lambda keys: removed.extend(keys))
    service.update_review(review.id, user.id, {"images": []})

    assert removed == [key]

# ---------- pagination ----------

def test_paginated_reviews_by_event_first_page(
    make_user, event, make_review
):
    # 행사 리뷰 25개 생성
    for _ in range(25):
        make_review(make_user(), event)

    result = service.get_paginated_reviews_by_event(event.id)

    assert result["total_count"] == 25
    assert result["page"] == 1
    assert result["size"] == 20
    assert len(result["reviews"]) == 20


def test_paginated_reviews_by_event_second_page(
    make_user, event, make_review
):
    for _ in range(25):
        make_review(make_user(), event)

    result = service.get_paginated_reviews_by_event(
        event.id,
        page=2,
        size=20,
    )

    assert result["total_count"] == 25
    assert result["page"] == 2
    assert result["size"] == 20
    assert len(result["reviews"]) == 5


def test_paginated_reviews_by_event_empty(event):
    result = service.get_paginated_reviews_by_event(event.id)

    assert result == {
        "total_count": 0,
        "page": 1,
        "size": 20,
        "reviews": [],
    }


def test_paginated_my_reviews(
    user, make_event, make_review
):
    # 한 사용자가 서로 다른 행사에 리뷰 25개 작성
    for _ in range(25):
        make_review(user, make_event())

    result = service.get_my_reviews(
        user.id,
        page=2,
        size=20,
    )

    assert result["total_count"] == 25
    assert result["page"] == 2
    assert result["size"] == 20
    assert len(result["reviews"]) == 5

    # 내 리뷰 응답에는 행사 정보도 포함되어야 한다.
    for review in result["reviews"]:
        assert "event" in review
        assert "title" in review["event"]

