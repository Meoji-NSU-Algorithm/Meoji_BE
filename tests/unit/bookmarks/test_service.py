"""bookmarks.service 단위 테스트 (실제 테스트 DB 사용)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.bookmarks import service
from app.domains.bookmarks.models import Bookmark


def _count():
    return db.session.scalar(db.select(db.func.count()).select_from(Bookmark))


def test_add_creates_then_is_idempotent(make_user, make_event):
    """처음엔 created=True, 같은 요청을 다시 하면 created=False이고 행은 1개 그대로다."""
    user, event = make_user(), make_event()
    first, created_first = service.add_bookmark(user.id, event.id)
    second, created_second = service.add_bookmark(user.id, event.id)
    assert (created_first, created_second) == (True, False)
    assert first.id == second.id
    assert _count() == 1


def test_add_unknown_user(make_event):
    with pytest.raises(BusinessException) as exc:
        service.add_bookmark(999999, make_event().id)
    assert exc.value.error_code == ErrorCode.USER_NOT_FOUND


def test_add_unknown_event(make_user):
    with pytest.raises(BusinessException) as exc:
        service.add_bookmark(make_user().id, 999999)
    assert exc.value.error_code == ErrorCode.EVENT_NOT_FOUND
    assert _count() == 0


def test_add_returns_existing_when_concurrent_insert_wins(make_user, make_event):
    """커밋 시 unique 위반이 나면(동시 요청) 롤백하고 이미 저장된 행을 created=False로 돌려준다."""
    user, event = make_user(), make_event()
    existing = Bookmark(user_id=user.id, event_id=event.id)
    db.session.add(existing)
    db.session.commit()

    # 처음 조회에서는 못 찾고(다른 요청이 아직 저장 전), 커밋에서 충돌하는 상황을 만든다.
    real_find = service._find_bookmark
    calls = {"n": 0}

    def fake_find(user_id, event_id):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(user_id, event_id)

    with patch.object(service, "_find_bookmark", side_effect=fake_find):
        bookmark, created = service.add_bookmark(user.id, event.id)
    assert created is False
    assert bookmark.id == existing.id
    assert _count() == 1


def test_add_reraises_integrity_error_when_row_still_missing(make_user, make_event):
    """충돌인데 기존 행도 없으면(다른 원인의 무결성 오류) 오류를 숨기지 않고 그대로 올린다."""
    user, event = make_user(), make_event()
    with patch.object(db.session, "commit", side_effect=IntegrityError("stmt", {}, Exception("x"))):
        with pytest.raises(IntegrityError):
            service.add_bookmark(user.id, event.id)


def test_list_is_empty_for_new_user(make_user):
    assert service.get_my_bookmarks(make_user().id) == {"total_count": 0, "events": []}


def test_list_unknown_user(app_ctx):
    with pytest.raises(BusinessException) as exc:
        service.get_my_bookmarks(999999)
    assert exc.value.error_code == ErrorCode.USER_NOT_FOUND


def test_list_orders_latest_saved_first_and_only_mine(make_user, make_event):
    """최근에 저장한 행사가 먼저 오고 다른 사용자의 북마크는 섞이지 않는다."""
    me, other = make_user(), make_user()
    old, new, others = make_event(title="오래된"), make_event(title="최신"), make_event(title="남의것")
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    db.session.add_all([
        Bookmark(user_id=me.id, event_id=old.id, created_at=base),
        Bookmark(user_id=me.id, event_id=new.id, created_at=base + timedelta(days=1)),
        Bookmark(user_id=other.id, event_id=others.id, created_at=base + timedelta(days=2)),
    ])
    db.session.commit()
    result = service.get_my_bookmarks(me.id)
    assert result["total_count"] == 2
    assert [e["title"] for e in result["events"]] == ["최신", "오래된"]


@pytest.mark.parametrize("is_free,price_type", [(True, "FREE"), (False, "PAID"), (None, "UNKNOWN")])
def test_list_price_type(make_user, make_event, is_free, price_type):
    user = make_user()
    event = make_event(is_free=is_free, image_url="https://example.test/e.jpg")
    service.add_bookmark(user.id, event.id)
    item = service.get_my_bookmarks(user.id)["events"][0]
    assert item["price_type"] == price_type
    assert item["image_url"] == "https://example.test/e.jpg"
    assert set(item) == {"id", "title", "image_url", "start_date", "end_date", "price_type"}


def test_remove_deletes_and_is_idempotent(make_user, make_event):
    user, event = make_user(), make_event()
    service.add_bookmark(user.id, event.id)
    expected = {"event_id": event.id, "is_bookmarked": False}
    assert service.remove_bookmark(user.id, event.id) == expected
    assert service.remove_bookmark(user.id, event.id) == expected
    assert _count() == 0


def test_remove_does_not_touch_other_users_bookmark(make_user, make_event):
    owner, other, event = make_user(), make_user(), make_event()
    service.add_bookmark(owner.id, event.id)
    service.remove_bookmark(other.id, event.id)
    assert db.session.scalar(select(Bookmark).where(Bookmark.user_id == owner.id)) is not None


def test_remove_unknown_user(make_event):
    with pytest.raises(BusinessException) as exc:
        service.remove_bookmark(999999, make_event().id)
    assert exc.value.error_code == ErrorCode.USER_NOT_FOUND
