"""도메인 폴더 이동 후 북마크의 기존 HTTP 계약과 최신 행사 모델 연결을 검사한다."""
import pytest
from flask_jwt_extended import create_access_token

from app.core.extensions import db
from app.domains.bookmarks.models import Bookmark


def test_add_duplicate_and_legacy_input(client, login, make_event):
    headers, _, user_id = login()
    event = make_event()
    for body in ({"eventId": event.id}, {"eventId": event.id}, {"event_id": event.id}):
        response = client.post("/api/bookmarks", json=body, headers=headers)
        assert response.status_code == 200
        assert response.get_json()["data"] == {"eventId": event.id, "isBookmarked": True}
    assert db.session.query(Bookmark).filter_by(user_id=user_id, event_id=event.id).count() == 1


@pytest.mark.parametrize("is_free,price_type", [(True, "FREE"), (False, "PAID"), (None, "UNKNOWN")])
def test_list_uses_current_event_image(client, login, make_event, is_free, price_type):
    headers, _, _ = login()
    event = make_event(image_url="https://example.test/event.jpg", is_free=is_free)
    assert not hasattr(event, "thumbnail_url")
    assert client.post("/api/bookmarks", json={"eventId": event.id}, headers=headers).status_code == 200
    response = client.get("/api/bookmarks/my", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["data"] == {
        "totalCount": 1,
        "events": [{
            "id": event.id, "title": event.title, "imageUrl": event.image_url,
            "startDate": event.start_date.isoformat(), "endDate": event.end_date.isoformat(),
            "priceType": price_type,
        }],
    }


def test_ownership_and_repeated_delete(client, login, make_event):
    owner, _, _ = login(kakao_id=1001)
    other, _, _ = login(kakao_id=1002)
    event = make_event()
    client.post("/api/bookmarks", json={"eventId": event.id}, headers=owner)
    assert client.get("/api/bookmarks/my", headers=other).get_json()["data"] == {
        "totalCount": 0, "events": [],
    }
    assert client.delete(f"/api/bookmarks/{event.id}", headers=other).status_code == 200
    assert db.session.query(Bookmark).count() == 1
    for _ in range(2):
        response = client.delete(f"/api/bookmarks/{event.id}", headers=owner)
        assert response.status_code == 200
        assert response.get_json()["data"] == {"eventId": event.id, "isBookmarked": False}
    assert client.get("/api/bookmarks/my", headers=owner).get_json()["data"] == {
        "totalCount": 0, "events": [],
    }


@pytest.mark.parametrize("body", [
    {}, {"eventId": 0}, {"eventId": -1}, {"eventId": 1.5}, {"eventId": "1"},
    {"eventId": True}, {"eventId": None}, {"eventId": 2_147_483_648},
    {"eventId": 1, "event_id": 1},
])
def test_invalid_input(client, login, body):
    headers, _, _ = login()
    response = client.post("/api/bookmarks", json=body, headers=headers)
    assert response.status_code == 400
    assert response.get_json()["code"] == "COMMON_INVALID_INPUT"
    assert db.session.query(Bookmark).count() == 0


def test_unknown_event(client, login):
    headers, _, _ = login()
    response = client.post("/api/bookmarks", json={"eventId": 999999}, headers=headers)
    assert response.status_code == 404
    assert response.get_json()["code"] == "EVENT_NOT_FOUND"


def test_missing_user(client, app_ctx):
    token = create_access_token(identity="999999")
    response = client.get("/api/bookmarks/my", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 404
    assert response.get_json()["code"] == "USER_NOT_FOUND"


@pytest.mark.parametrize("method,path", [
    ("post", "/api/bookmarks"), ("get", "/api/bookmarks/my"), ("delete", "/api/bookmarks/1"),
])
def test_requires_login(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_removed_root_get(client):
    response = client.get("/api/bookmarks")
    assert response.status_code == 405
    assert "POST" in response.headers["Allow"]
