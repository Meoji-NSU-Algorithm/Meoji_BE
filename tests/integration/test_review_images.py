"""리뷰 이미지 업로드·연결·삭제 흐름. 저장소는 메모리 가짜로 바꾸고 나머지는 실제 앱/DB를 쓴다."""
import io

import pytest
from PIL import Image

from app.core.extensions import db
from app.domains.reviews import images, storage_client
from app.domains.reviews.models import Review

PUBLIC = "http://img.test/review-images"


class FakeS3:
    """storage_client._client()가 돌려주는 boto3 클라이언트 대신 쓰는 메모리 저장소."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = (Body, ContentType)

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)


@pytest.fixture()
def s3(app, monkeypatch):
    # kakao_profiles 픽스처처럼 외부 통신 지점(모듈 속성)만 바꾼다.
    fake = FakeS3()
    monkeypatch.setattr(storage_client, "_client", lambda: fake)
    monkeypatch.setitem(app.config, "S3_BUCKET", "review-images")
    monkeypatch.setitem(app.config, "S3_PUBLIC_URL", PUBLIC)
    return fake


def _jpeg(size=(2000, 1000)):
    out = io.BytesIO()
    Image.new("RGB", size, "blue").save(out, "JPEG")
    out.seek(0)
    return out


def _upload(client, headers, file=None, name="photo.jpg"):
    return client.post(
        "/api/reviews/images",
        headers=headers,
        data={"image": (file or _jpeg(), name)},
        content_type="multipart/form-data",
    )


def test_upload_converts_and_stores_webp(client, login, s3):
    headers, _, _ = login()
    response = _upload(client, headers)
    assert response.status_code == 201
    key = response.json["data"]["key"]
    assert images.KEY_PATTERN.match(key)
    assert response.json["data"]["url"] == f"{PUBLIC}/{key}"
    body, content_type = s3.objects[key]
    assert content_type == "image/webp"
    assert Image.open(io.BytesIO(body)).size == (1600, 800)


def test_upload_requires_login_and_file(client, login, s3):
    assert _upload(client, {}).status_code == 401
    headers, _, _ = login()
    response = client.post("/api/reviews/images", headers=headers, data={}, content_type="multipart/form-data")
    assert response.status_code == 400
    assert response.json["code"] == "COMMON_INVALID_INPUT"


def test_upload_rejects_non_image_and_too_large(client, login, s3, monkeypatch):
    headers, _, _ = login()
    response = _upload(client, headers, io.BytesIO(b"<?php echo 1; ?>"), "x.jpg")
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_INVALID")
    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 100)
    response = _upload(client, headers)
    assert (response.status_code, response.json["code"]) == (413, "REVIEW_IMAGE_TOO_LARGE")
    assert s3.objects == {}


def test_upload_without_storage_config_is_503(client, login, app, monkeypatch):
    for key in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.setitem(app.config, key, None)
    monkeypatch.delitem(app.extensions, "review_storage_client", raising=False)
    headers, _, _ = login()
    response = _upload(client, headers)
    assert (response.status_code, response.json["code"]) == (503, "REVIEW_IMAGE_STORAGE_UNAVAILABLE")


def test_review_images_create_update_delete(client, login, make_event, s3):
    headers, _, _ = login()
    eid = make_event().id
    k1, k2, k3 = (_upload(client, headers).json["data"]["key"] for _ in range(3))

    created = client.post("/api/reviews", headers=headers,
                          json={"event_id": eid, "rating": 4, "content": "사진 후기", "images": [k1, k2]})
    assert created.status_code == 201
    assert created.json["data"]["images"] == [{"key": k, "url": f"{PUBLIC}/{k}"} for k in (k1, k2)]
    rid = created.json["data"]["id"]

    # 목록 조회와 행사 상세에도 같은 형식으로 내려간다.
    assert client.get("/api/reviews/my", headers=headers).json["data"][0]["images"][0]["key"] == k1
    assert client.get(f"/api/events/{eid}", headers=headers).json["data"]["reviews"][0]["images"][1]["key"] == k2

    # 수정은 목록 전체 교체이고, 빠진 이미지는 저장소에서도 지운다.
    updated = client.put(f"/api/reviews/{rid}", headers=headers, json={"images": [k2, k3]})
    assert [i["key"] for i in updated.json["data"]["images"]] == [k2, k3]
    assert k1 not in s3.objects and k2 in s3.objects

    # images 없이 수정하면 이미지는 그대로다.
    kept = client.put(f"/api/reviews/{rid}", headers=headers, json={"content": "내용만 수정"})
    assert [i["key"] for i in kept.json["data"]["images"]] == [k2, k3]

    assert client.delete(f"/api/reviews/{rid}", headers=headers).status_code == 200
    assert k2 not in s3.objects and k3 not in s3.objects


def test_review_without_images_returns_empty_list(client, login, make_event, s3):
    headers, _, _ = login()
    created = client.post("/api/reviews", headers=headers,
                          json={"event_id": make_event().id, "rating": 5, "content": "글만"})
    assert created.json["data"]["images"] == []


@pytest.mark.parametrize("bad", [
    ["https://evil.example/a.webp"],
    ["reviews/" + "a" * 32 + ".jpg"],
    ["reviews/" + "a" * 32 + ".webp"] * 6,
    "reviews/x.webp",
])
def test_review_rejects_invalid_images(client, login, make_event, s3, bad):
    headers, _, _ = login()
    response = client.post("/api/reviews", headers=headers,
                           json={"event_id": make_event().id, "rating": 5, "content": "x", "images": bad})
    assert response.status_code == 400
    assert response.json["code"] == "COMMON_INVALID_INPUT"


def test_review_read_without_storage_config_returns_null_url(client, login, make_event, s3, app, monkeypatch):
    """저장소 설정이 없어도 리뷰 조회는 200이고 url만 null이다."""
    headers, _, _ = login()
    eid = make_event().id
    key = _upload(client, headers).json["data"]["key"]
    client.post("/api/reviews", headers=headers, json={"event_id": eid, "rating": 4, "content": "후기", "images": [key]})
    monkeypatch.setitem(app.config, "S3_PUBLIC_URL", None)
    for name in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.setitem(app.config, name, None)

    for path in (f"/api/events/{eid}", f"/api/reviews/event/{eid}", "/api/reviews/my"):
        assert client.get(path, headers=headers).status_code == 200, path
    detail = client.get(f"/api/events/{eid}", headers=headers).json["data"]
    assert detail["reviews"][0]["images"] == [{"key": key, "url": None}]


def _review(client, headers, event_id, keys):
    return client.post("/api/reviews", headers=headers,
                       json={"event_id": event_id, "rating": 4, "content": "후기", "images": keys})


def test_cannot_attach_or_delete_other_users_image(client, login, make_event, s3):
    """남의 리뷰에 붙은 key를 가져다 붙이고 수정·삭제해 남의 이미지를 지울 수 없다."""
    a_headers, _, _ = login(kakao_id=8001)
    b_headers, _, _ = login(kakao_id=8002)
    e1, e2 = make_event().id, make_event().id
    a_key = _upload(client, a_headers).json["data"]["key"]
    assert _review(client, a_headers, e1, [a_key]).status_code == 201

    # 작성 시 거부
    response = _review(client, b_headers, e1, [a_key])
    assert (response.status_code, response.json["code"]) == (409, "REVIEW_IMAGE_ALREADY_ATTACHED")

    # 수정 시 거부, 다른 필드도 바뀌지 않는다
    b_key = _upload(client, b_headers).json["data"]["key"]
    b_review = _review(client, b_headers, e2, [b_key]).json["data"]["id"]
    response = client.put(f"/api/reviews/{b_review}", headers=b_headers,
                          json={"content": "바뀌면 안 됨", "images": [b_key, a_key]})
    assert (response.status_code, response.json["code"]) == (409, "REVIEW_IMAGE_ALREADY_ATTACHED")
    db.session.expire_all()
    assert db.session.get(Review, b_review).content == "후기"

    # B가 자기 리뷰를 지워도 A의 이미지는 남는다
    assert client.delete(f"/api/reviews/{b_review}", headers=b_headers).status_code == 200
    assert a_key in s3.objects and b_key not in s3.objects


def test_own_images_can_be_kept_on_update(client, login, make_event, s3):
    """자기 리뷰에 이미 붙은 key를 그대로 두고 수정하는 것은 허용한다."""
    headers, _, _ = login()
    k1, k2 = (_upload(client, headers).json["data"]["key"] for _ in range(2))
    rid = _review(client, headers, make_event().id, [k1]).json["data"]["id"]
    response = client.put(f"/api/reviews/{rid}", headers=headers, json={"images": [k1, k2]})
    assert response.status_code == 200
    assert [i["key"] for i in response.json["data"]["images"]] == [k1, k2]


def test_rejects_duplicate_keys_in_one_review(client, login, make_event, s3):
    headers, _, _ = login()
    key = _upload(client, headers).json["data"]["key"]
    response = _review(client, headers, make_event().id, [key, key])
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")


def test_delete_keeps_images_still_referenced_by_other_reviews(client, login, make_event, s3):
    """수정 전 데이터처럼 두 리뷰가 같은 key를 가리켜도, 남은 리뷰의 이미지는 지우지 않는다."""
    a_headers, _, _ = login(kakao_id=8101)
    b_headers, _, _ = login(kakao_id=8102)
    eid = make_event().id
    key = _upload(client, a_headers).json["data"]["key"]
    _review(client, a_headers, eid, [key])
    b_review = _review(client, b_headers, eid, []).json["data"]["id"]
    # API로는 만들 수 없는 공유 상태를 DB에 직접 만든다
    db.session.get(Review, b_review).images = [key]
    db.session.commit()

    assert client.delete(f"/api/reviews/{b_review}", headers=b_headers).status_code == 200
    assert key in s3.objects


def test_request_body_over_limit_is_413(client, login, app, s3):
    """MAX_CONTENT_LENGTH를 넘는 본문은 다 받기 전에 413으로 거절한다."""
    headers, _, _ = login()
    response = _upload(client, headers, io.BytesIO(b"0" * (app.config["MAX_CONTENT_LENGTH"] + 1)))
    assert (response.status_code, response.json["code"]) == (413, "COMMON_PAYLOAD_TOO_LARGE")


def test_post_commit_reference_check_failure_does_not_fail_request(client, login, make_event, s3, monkeypatch):
    """커밋 뒤 참조 확인 쿼리가 실패해도 삭제는 200이고, 확인 못 한 이미지는 지우지 않는다."""
    from sqlalchemy.exc import OperationalError
    from app.domains.reviews import service

    headers, _, _ = login()
    key = _upload(client, headers).json["data"]["key"]
    rid = _review(client, headers, make_event().id, [key]).json["data"]["id"]

    def fail(*args, **kwargs):
        raise OperationalError("SELECT", {}, Exception("db down"))

    monkeypatch.setattr(service, "_keys_attached_elsewhere", fail)
    assert client.delete(f"/api/reviews/{rid}", headers=headers).status_code == 200
    assert db.session.get(Review, rid) is None
    assert key in s3.objects


# ---------- 리뷰에 붙지 않은 업로드 정리 ----------
from datetime import datetime, timedelta, timezone

from app.domains.reviews import service as review_service
from app.domains.reviews.models import ReviewImageUpload


def _age(key, hours):
    """업로드 기록을 hours 시간 전으로 돌린다."""
    upload = db.session.get(ReviewImageUpload, key)
    upload.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    db.session.commit()


def test_upload_is_recorded_until_attached(client, login, make_event, s3):
    headers, _, uid = login()
    key = _upload(client, headers).json["data"]["key"]
    assert db.session.get(ReviewImageUpload, key).user_id == uid

    _review(client, headers, make_event().id, [key])
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is None


def test_update_marks_new_images_attached(client, login, make_event, s3):
    headers, _, _ = login()
    rid = _review(client, headers, make_event().id, []).json["data"]["id"]
    key = _upload(client, headers).json["data"]["key"]
    client.put(f"/api/reviews/{rid}", headers=headers, json={"images": [key]})
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is None


def test_cleanup_deletes_only_old_unattached_uploads(client, login, make_event, s3):
    headers, _, _ = login()
    old, recent = (_upload(client, headers).json["data"]["key"] for _ in range(2))
    _age(old, 25)
    _age(recent, 1)

    assert review_service.cleanup_unattached_uploads() == 1
    assert old not in s3.objects and recent in s3.objects
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, old) is None
    assert db.session.get(ReviewImageUpload, recent) is not None


def test_cleanup_keeps_file_if_review_still_uses_it(client, login, make_event, s3):
    """기록이 남아 있어도 리뷰에 붙은 이미지는 파일을 지우지 않고 기록만 지운다."""
    headers, _, uid = login()
    key = _upload(client, headers).json["data"]["key"]
    _review(client, headers, make_event().id, [key])
    db.session.add(ReviewImageUpload(key=key, user_id=uid))
    db.session.commit()
    _age(key, 25)

    assert review_service.cleanup_unattached_uploads() == 0
    assert key in s3.objects
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is None


def test_upload_does_not_run_cleanup(client, login, s3):
    """정리는 스케줄러가 맡으므로 업로드 요청은 오래된 미첨부 업로드를 지우지 않는다. (#36)"""
    headers, _, _ = login()
    old = _upload(client, headers).json["data"]["key"]
    _age(old, 25)
    _upload(client, headers)
    assert old in s3.objects


def test_cleanup_keeps_record_when_storage_delete_fails(client, login, s3, monkeypatch):
    """저장소 삭제가 실패하면 기록을 남겨 다음 정리 때 다시 시도한다. (#36)"""
    from botocore.exceptions import BotoCoreError

    headers, _, _ = login()
    key = _upload(client, headers).json["data"]["key"]
    _age(key, 25)

    real_delete = s3.delete_objects

    def fail(**kwargs):
        raise BotoCoreError()

    monkeypatch.setattr(s3, "delete_objects", fail)
    assert review_service.cleanup_unattached_uploads() == 0
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is not None

    monkeypatch.setattr(s3, "delete_objects", real_delete)
    assert review_service.cleanup_unattached_uploads() == 1
    assert key not in s3.objects
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, key) is None


def test_cleanup_keeps_record_only_for_partially_failed_keys(client, login, s3, monkeypatch):
    """S3가 일부 key만 실패로 돌려주면 그 key의 기록만 남긴다. (#36)"""
    headers, _, _ = login()
    ok, bad = (_upload(client, headers).json["data"]["key"] for _ in range(2))
    _age(ok, 25)
    _age(bad, 25)

    real_delete = s3.delete_objects

    def partial(Bucket, Delete):
        real_delete(Bucket, {"Objects": [obj for obj in Delete["Objects"] if obj["Key"] != bad]})
        return {"Errors": [{"Key": bad, "Code": "InternalError"}]}

    monkeypatch.setattr(s3, "delete_objects", partial)
    assert review_service.cleanup_unattached_uploads() == 1
    db.session.expire_all()
    assert db.session.get(ReviewImageUpload, ok) is None
    assert db.session.get(ReviewImageUpload, bad) is not None


# ---------- 회원 탈퇴 ----------
def test_withdraw_deletes_review_images_except_shared(client, login, make_event, s3, monkeypatch):
    """탈퇴하면 리뷰 이미지를 지우되, 다른 사용자의 리뷰가 참조하는 이미지와 남의 이미지는 남긴다."""
    from app.domains.auth import kakao_client

    monkeypatch.setattr(kakao_client, "unlink_kakao_user", lambda kakao_id: None)
    a_headers, _, _ = login(kakao_id=8201)
    b_headers, _, _ = login(kakao_id=8202)
    eid = make_event().id
    own, shared = (_upload(client, a_headers).json["data"]["key"] for _ in range(2))
    other = _upload(client, b_headers).json["data"]["key"]
    _review(client, a_headers, eid, [own, shared])
    b_review = _review(client, b_headers, eid, [other]).json["data"]["id"]
    # API로는 만들 수 없는 공유 상태를 DB에 직접 만든다
    db.session.get(Review, b_review).images = [other, shared]
    db.session.commit()

    assert client.delete("/api/users/me", headers=a_headers).status_code == 200
    assert own not in s3.objects
    assert shared in s3.objects and other in s3.objects


def test_withdraw_succeeds_when_storage_delete_fails(client, login, make_event, s3, monkeypatch):
    """저장소 삭제가 실패해도 탈퇴는 성공한다."""
    from botocore.exceptions import BotoCoreError
    from app.domains.auth import kakao_client

    monkeypatch.setattr(kakao_client, "unlink_kakao_user", lambda kakao_id: None)
    headers, _, uid = login()
    key = _upload(client, headers).json["data"]["key"]
    _review(client, headers, make_event().id, [key])

    def fail(**kwargs):
        raise BotoCoreError()

    monkeypatch.setattr(s3, "delete_objects", fail)
    assert client.delete("/api/users/me", headers=headers).status_code == 200
    assert client.get("/api/users/me", headers=headers).status_code == 401


def test_my_reviews_include_event_author_and_images(client, login, make_event, s3):
    """내 리뷰에는 행사 정보, 작성자, 이미지 {key, url}이 함께 나온다."""
    headers, _, uid = login(nickname="나")
    event = make_event(title="내 행사", image_url="https://example.com/e.jpg")
    key = _upload(client, headers).json["data"]["key"]
    _review(client, headers, event.id, [key])

    review = client.get("/api/reviews/my", headers=headers).json["data"][0]
    assert review["event"] == {
        "id": event.id, "title": "내 행사", "image_url": "https://example.com/e.jpg",
        "end_date": event.end_date.isoformat(),
    }
    assert review["author"]["id"] == uid
    assert review["images"] == [{"key": key, "url": f"{PUBLIC}/{key}"}]


# ---------- 이슈 #34: 업로더 소유권·존재 검증 ----------
def test_rejects_key_never_uploaded(client, login, make_event, s3):
    headers, _, _ = login()
    response = _review(client, headers, make_event().id, ["reviews/" + "a" * 32 + ".webp"])
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_NOT_UPLOADED")


def test_rejects_other_users_unattached_key(client, login, make_event, s3):
    a_headers, _, _ = login(kakao_id=8301)
    b_headers, _, _ = login(kakao_id=8302)
    a_key = _upload(client, a_headers).json["data"]["key"]
    response = _review(client, b_headers, make_event().id, [a_key])
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_NOT_UPLOADED")
    # A는 그대로 자기 리뷰에 붙일 수 있다
    assert _review(client, a_headers, make_event().id, [a_key]).status_code == 201


def test_rejects_key_cleaned_after_ttl(client, login, make_event, s3):
    headers, _, _ = login()
    key = _upload(client, headers).json["data"]["key"]
    _age(key, 25)
    assert review_service.cleanup_unattached_uploads() == 1
    response = _review(client, headers, make_event().id, [key])
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_NOT_UPLOADED")


def test_update_rejects_not_owned_key_without_changing_review(client, login, make_event, s3):
    headers, _, _ = login()
    rid = _review(client, headers, make_event().id, []).json["data"]["id"]
    response = client.put(f"/api/reviews/{rid}", headers=headers,
                          json={"content": "바뀌면 안 됨", "images": ["reviews/" + "b" * 32 + ".webp"]})
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_NOT_UPLOADED")
    db.session.expire_all()
    assert db.session.get(Review, rid).content == "후기"


def test_same_key_attached_twice_rejected_even_if_check_is_bypassed(client, login, make_event, s3, monkeypatch):
    """동시 첨부 경합: 두 요청이 '다른 리뷰에 붙었는가' 검사를 모두 통과해도 업로드 기록은 한 번만 쓸 수 있다."""
    headers, _, _ = login()
    key = _upload(client, headers).json["data"]["key"]
    monkeypatch.setattr(review_service, "_ensure_images_not_attached", lambda *args, **kwargs: None)
    assert _review(client, headers, make_event().id, [key]).status_code == 201
    response = _review(client, headers, make_event().id, [key])
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_NOT_UPLOADED")
