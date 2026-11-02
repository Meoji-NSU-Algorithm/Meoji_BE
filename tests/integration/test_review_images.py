"""리뷰 이미지 업로드·연결·삭제 흐름. 저장소는 메모리 가짜로 바꾸고 나머지는 실제 앱/DB를 쓴다."""
import io

import pytest
from PIL import Image

from app.domains.reviews import images

PUBLIC = "http://img.test/review-images"


class FakeS3:
    """images._client()가 돌려주는 boto3 클라이언트 대신 쓰는 메모리 저장소."""

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
    monkeypatch.setattr(images, "_client", lambda: fake)
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
