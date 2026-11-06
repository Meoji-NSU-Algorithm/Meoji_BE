"""행사 상세 조회수의 사용자당 하루 1회 집계 HTTP 통합 테스트. (PR #39)"""
from unittest.mock import MagicMock

from app.core.extensions import db
from app.domains.auth import kakao_client
from app.domains.events.models import Event, EventUserDailyView


def _view_count(event_id):
    db.session.remove()  # REPEATABLE READ 스냅샷을 버리고 새로 읽는다
    return db.session.get(Event, event_id).view_count


def test_same_user_repeated_detail_counts_once(client, login, make_event):
    headers, _, _ = login(kakao_id=5001)
    event = make_event()

    for _ in range(3):
        assert client.get(f"/api/events/{event.id}", headers=headers).status_code == 200

    assert _view_count(event.id) == 1


def test_different_users_each_count_once(client, login, make_event):
    first, _, _ = login(kakao_id=5011)
    second, _, _ = login(kakao_id=5012)
    event = make_event()

    client.get(f"/api/events/{event.id}", headers=first)
    client.get(f"/api/events/{event.id}", headers=second)
    client.get(f"/api/events/{event.id}", headers=first)

    assert _view_count(event.id) == 2


def test_same_user_different_events_count_separately(client, login, make_event):
    headers, _, _ = login(kakao_id=5021)
    one, two = make_event(), make_event()

    client.get(f"/api/events/{one.id}", headers=headers)
    client.get(f"/api/events/{two.id}", headers=headers)

    assert (_view_count(one.id), _view_count(two.id)) == (1, 1)


def test_head_request_does_not_record_view(client, login, make_event):
    headers, _, _ = login(kakao_id=5031)
    event = make_event()

    client.head(f"/api/events/{event.id}", headers=headers)

    assert _view_count(event.id) == 0
    db.session.remove()
    assert db.session.scalar(db.select(db.func.count()).select_from(EventUserDailyView)) == 0


def test_withdraw_removes_user_daily_view_rows(client, login, make_event, monkeypatch):
    """탈퇴하면 event_user_daily_views 행도 CASCADE로 지워지고, 행사 조회수는 그대로다."""
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", MagicMock())
    headers, _, user_id = login(kakao_id=5041)
    event = make_event()
    client.get(f"/api/events/{event.id}", headers=headers)
    db.session.remove()
    assert db.session.scalar(db.select(db.func.count()).select_from(EventUserDailyView)) == 1

    assert client.delete("/api/users/me", headers=headers).status_code == 200

    db.session.remove()
    assert db.session.scalar(db.select(db.func.count()).select_from(EventUserDailyView)) == 0
    assert db.session.get(Event, event.id).view_count == 1
