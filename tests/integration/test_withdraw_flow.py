"""회원 탈퇴(DELETE /api/users/me) HTTP 통합 테스트. 카카오 서버는 호출하지 않는다."""
from unittest.mock import MagicMock

import requests

from app.core.extensions import db
from app.domains.bookmarks.models import Bookmark
from app.domains.events.models import EventUserDailyView
from app.domains.auth import kakao_client
from app.domains.reviews.models import Review
from app.domains.users.models import User
from tests.integration.test_auth_flow import assert_error
from tests.integration.test_events_reviews_flow import post_review
from tests.integration.test_review_images import _files, _jpeg, _post


def _user_exists(user_id):
    db.session.expire_all()
    return db.session.get(User, user_id) is not None


def _review_user_ids():
    db.session.expire_all()
    return set(db.session.scalars(db.select(Review.user_id)))


def test_withdraw_deletes_user_and_unlinks_kakao(client, login, monkeypatch):
    """탈퇴하면 200, 유저 행이 사라지고 카카오 연결 끊기가 kakao_id로 한 번 호출된다."""
    unlink = MagicMock()
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", unlink)
    h, _, uid = login(kakao_id=777)

    resp = client.delete("/api/users/me", headers=h)

    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert not _user_exists(uid)
    unlink.assert_called_once_with(777)


def test_withdraw_cascades_only_own_reviews(client, refs, make_event, login, monkeypatch):
    """탈퇴하면 본인 리뷰만 CASCADE로 삭제되고 다른 유저의 리뷰는 남는다."""
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", MagicMock())
    e1, e2 = make_event().id, make_event().id
    h1, _, uid1 = login(kakao_id=1)
    h2, _, uid2 = login(kakao_id=2)
    assert post_review(client, h1, e1).status_code == 201
    assert post_review(client, h1, e2).status_code == 201
    assert post_review(client, h2, e1).status_code == 201
    assert _review_user_ids() == {uid1, uid2}

    assert client.delete("/api/users/me", headers=h1).status_code == 200

    assert not _user_exists(uid1)
    assert _user_exists(uid2)
    db.session.expire_all()
    remaining = db.session.scalars(db.select(Review)).all()
    assert [r.user_id for r in remaining] == [uid2]


def test_access_token_revoked_after_withdraw(client, login, monkeypatch):
    """탈퇴에 쓴 access token은 이후 401 AUTH_TOKEN_REVOKED."""
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", MagicMock())
    h, _, _ = login()
    client.delete("/api/users/me", headers=h)
    assert_error(client.get("/api/users/me", headers=h), 401, "AUTH_TOKEN_REVOKED")


def test_refresh_token_rejected_after_withdraw(client, login, bearer, monkeypatch):
    """탈퇴한 유저의 refresh 토큰은 재발급할 수 없다(401 AUTH_TOKEN_INVALID)."""
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", MagicMock())
    h, tokens, _ = login()
    client.delete("/api/users/me", headers=h)
    assert_error(client.post("/api/auth/refresh", headers=bearer(tokens["refresh_token"])),
                 401, "AUTH_TOKEN_INVALID")


def test_second_withdraw_with_old_token_returns_401(client, login, monkeypatch):
    """같은 토큰으로 다시 탈퇴를 요청하면 401 AUTH_TOKEN_REVOKED이고 카카오는 다시 호출되지 않는다."""
    unlink = MagicMock()
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", unlink)
    h, _, _ = login()
    client.delete("/api/users/me", headers=h)
    assert_error(client.delete("/api/users/me", headers=h), 401, "AUTH_TOKEN_REVOKED")
    assert unlink.call_count == 1


def test_withdraw_requires_token(client):
    """토큰 없이는 401."""
    assert_error(client.delete("/api/users/me"), 401, "AUTH_UNAUTHORIZED")


def test_withdraw_succeeds_when_kakao_http_fails(client, app_ctx, login, monkeypatch):
    """카카오 HTTP 호출이 연결 오류로 실패해도 탈퇴는 200으로 끝나고 유저는 삭제된다."""
    h, _, uid = login(kakao_id=555)
    monkeypatch.setitem(app_ctx.config, "KAKAO_ADMIN_KEY", "admin-key")
    post = MagicMock(side_effect=requests.ConnectionError("boom"))
    monkeypatch.setattr(kakao_client.requests, "post", post)

    resp = client.delete("/api/users/me", headers=h)

    assert resp.status_code == 200
    post.assert_called_once()
    assert post.call_args.kwargs["data"]["target_id"] == 555
    assert not _user_exists(uid)


def test_withdraw_succeeds_without_admin_key(client, app_ctx, login, monkeypatch):
    """KAKAO_ADMIN_KEY가 없으면 연결 끊기만 건너뛰고 탈퇴는 완료된다."""
    h, _, uid = login()
    monkeypatch.setitem(app_ctx.config, "KAKAO_ADMIN_KEY", None)
    post = MagicMock()
    monkeypatch.setattr(kakao_client.requests, "post", post)

    assert client.delete("/api/users/me", headers=h).status_code == 200
    post.assert_not_called()
    assert not _user_exists(uid)


def test_withdraw_deletes_all_my_data(client, login, make_event, s3, monkeypatch):
    """탈퇴하면 리뷰·리뷰 사진·북마크·조회 기록·프로필 사진이 모두 지워지고, 다른 유저 것은 남는다."""
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", MagicMock())
    h1, _, uid1 = login(kakao_id=1)
    h2, _, uid2 = login(kakao_id=2)
    event = make_event()

    for headers in (h1, h2):
        assert _post(client, headers, event.id, _files(1)).status_code == 201           # 리뷰 + 리뷰 사진
        client.post("/api/bookmarks", json={"eventId": event.id}, headers=headers)      # 북마크
        client.get(f"/api/events/{event.id}", headers=headers)                          # 조회 기록
    client.put("/api/users/me/profile-image", headers=h1,                               # 프로필 사진
               content_type="multipart/form-data", data={"image": [(_jpeg(), "me.jpg")]})
    for model in (Review, Bookmark, EventUserDailyView):
        db.session.expire_all()
        assert {row.user_id for row in db.session.scalars(db.select(model))} == {uid1, uid2}
    files_before = set(s3.objects)
    assert len(files_before) == 3                       # 리뷰 사진 2장 + 프로필 사진 1장

    assert client.delete("/api/users/me", headers=h1).status_code == 200

    db.session.expire_all()
    for model in (Review, Bookmark, EventUserDailyView):
        assert {row.user_id for row in db.session.scalars(db.select(model))} == {uid2}
    assert not any(key.startswith("profiles/") for key in s3.objects)
    assert set(s3.objects) < files_before                # 내 파일만 지워지고 다른 유저 파일은 남음
    assert len(s3.objects) == 1
