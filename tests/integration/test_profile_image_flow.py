"""프로필 사진 변경 흐름. 카카오와 저장소만 가짜로 바꾸고 나머지는 실제 앱/DB를 쓴다."""
import io

import pytest
from PIL import Image

from app.core.extensions import db
from app.domains.users import service as user_service
from tests.integration.conftest import PUBLIC
from tests.integration.test_review_images import _jpeg


def _upload(client, headers, files):
    return client.put("/api/users/me/profile-image", headers=headers,
                      content_type="multipart/form-data", data={"image": files})


def _me(client, headers):
    return client.get("/api/users/me", headers=headers).json["data"]


def _relogin_with_kakao_photo(client, kakao_profiles, photo, kakao_id=1001):
    """카카오 사진을 바꾼 뒤 다시 로그인한다."""
    kakao_profiles["again"] = {"kakao_id": kakao_id, "email": f"user{kakao_id}@test.com",
                               "nickname": f"user{kakao_id}", "profile_image": photo}
    tokens = client.post("/api/auth/kakao", json={"code": "again"}).json["data"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_upload_stores_512_webp_and_survives_relogin(client, login, kakao_profiles, s3):
    """512px webp로 저장되고, 카카오 사진이 바뀐 뒤 다시 로그인해도 직접 올린 사진이 유지된다."""
    headers, _, _ = login()
    response = _upload(client, headers, [(_jpeg((2000, 1000)), "me.jpg")])
    assert response.status_code == 200
    url = response.json["data"]["profile_image"]
    key = url.removeprefix(f"{PUBLIC}/")
    assert key.startswith("profiles/")
    body, content_type = s3.objects[key]
    assert content_type == "image/webp" and Image.open(io.BytesIO(body)).size == (512, 256)

    headers = _relogin_with_kakao_photo(client, kakao_profiles, "http://kakao/new")
    assert _me(client, headers)["profile_image"] == url


def test_upload_again_deletes_old_file(client, login, s3):
    headers, _, _ = login()
    first = _upload(client, headers, [(_jpeg(), "a.jpg")]).json["data"]["profile_image"]
    second = _upload(client, headers, [(_jpeg(), "b.jpg")]).json["data"]["profile_image"]
    assert first != second
    assert list(s3.objects) == [second.removeprefix(f"{PUBLIC}/")]


@pytest.mark.parametrize("files, status, code", [
    ([], 400, "COMMON_INVALID_INPUT"),                                             # 사진 없음
    ([(_jpeg(), "a.jpg"), (_jpeg(), "b.jpg")], 400, "COMMON_INVALID_INPUT"),       # 2장
    ([(io.BytesIO(b"<?php echo 1; ?>"), "x.jpg")], 400, "IMAGE_INVALID"),          # 이미지가 아님
])
def test_upload_rejects_bad_requests_without_storing(client, login, s3, files, status, code):
    headers, _, _ = login()
    response = _upload(client, headers, files)
    assert (response.status_code, response.json["code"]) == (status, code)
    assert s3.objects == {}


def test_upload_over_limit_is_413(client, login, s3, monkeypatch):
    monkeypatch.setattr(user_service, "PROFILE_MAX_UPLOAD_BYTES", 100)
    headers, _, _ = login()
    response = _upload(client, headers, [(_jpeg(), "a.jpg")])
    assert (response.status_code, response.json["code"]) == (413, "IMAGE_TOO_LARGE")
    assert s3.objects == {}


def test_failed_commit_deletes_new_file(client, login, s3, monkeypatch):
    """사진은 올라갔는데 DB 저장이 실패하면 올린 사진을 지운다."""
    headers, _, _ = login()

    def broken_commit():
        raise RuntimeError("db down")

    monkeypatch.setattr(db.session, "commit", broken_commit)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    response = _upload(client, headers, [(_jpeg(), "a.jpg")])
    assert response.status_code == 500
    assert s3.objects == {}


def test_default_then_kakao(client, login, kakao_profiles, s3):
    headers, _, _ = login()
    _upload(client, headers, [(_jpeg(), "a.jpg")])

    response = client.put("/api/users/me/profile-image/source", headers=headers, json={"source": "default"})
    assert response.status_code == 200
    assert response.json["data"]["profile_image"] is None
    assert s3.objects == {}                                   # 직접 올린 사진 파일도 지워짐

    headers = _relogin_with_kakao_photo(client, kakao_profiles, "http://kakao/new")
    assert _me(client, headers)["profile_image"] is None      # 기본 이미지 유지

    response = client.put("/api/users/me/profile-image/source", headers=headers, json={"source": "kakao"})
    assert response.json["data"]["profile_image"] == "http://kakao/new"


@pytest.mark.parametrize("body", [{}, {"source": "custom"}, {"source": "x"}])
def test_source_rejects_invalid_value(client, login, body):
    headers, _, _ = login()
    response = client.put("/api/users/me/profile-image/source", headers=headers, json=body)
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")


def test_review_author_shows_uploaded_photo(client, login, make_event, s3):
    headers, _, _ = login()
    url = _upload(client, headers, [(_jpeg(), "a.jpg")]).json["data"]["profile_image"]
    created = client.post("/api/reviews", headers=headers, json={"event_id": make_event().id, "rating": 5, "content": "x"})
    assert created.status_code == 201
    assert client.get("/api/reviews/my", headers=headers).json["data"][0]["author"]["profile_image"] == url


def test_withdraw_deletes_uploaded_photo(client, login, s3, monkeypatch):
    from app.domains.auth import kakao_client
    monkeypatch.setattr(kakao_client, "unlink_kakao_user", lambda kakao_id: None)
    headers, _, _ = login()
    _upload(client, headers, [(_jpeg(), "a.jpg")])
    assert s3.objects
    assert client.delete("/api/users/me", headers=headers).status_code == 200
    assert s3.objects == {}


def test_requires_login(client):
    assert client.put("/api/users/me/profile-image").status_code == 401
    assert client.put("/api/users/me/profile-image/source", json={"source": "kakao"}).status_code == 401
