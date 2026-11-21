"""리뷰 사진 첨부(리뷰 작성·수정 요청에 같이 올림)와 삭제 흐름. 저장소는 메모리 가짜로 바꾸고 나머지는 실제 앱/DB를 쓴다."""
import io
import json

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


def _files(n):
    return [(_jpeg(), f"p{i}.jpg") for i in range(n)]


def _post(client, headers, event_id, files=None, **fields):
    """사진과 함께 리뷰를 작성한다. 본문은 data 필드에 JSON 문자열로 넣는다."""
    data = {"event_id": event_id, "rating": 4, "content": "후기", **fields}
    return client.post("/api/reviews", headers=headers, content_type="multipart/form-data",
                       data={"data": json.dumps(data), "images": files if files is not None else _files(1)})


def _put(client, headers, review_id, files=(), **fields):
    form = {"images": list(files)}
    if fields:
        form["data"] = json.dumps(fields)
    return client.put(f"/api/reviews/{review_id}", headers=headers, content_type="multipart/form-data", data=form)


def _keys(response):
    return [image["key"] for image in response.json["data"]["images"]]


def test_create_with_images_stores_webp(client, login, make_event, s3):
    headers, _, _ = login()
    eid = make_event().id
    response = _post(client, headers, eid, _files(2))
    assert response.status_code == 201
    keys = _keys(response)
    assert len(keys) == 2 and all(images.KEY_PATTERN.match(k) for k in keys)
    assert response.json["data"]["images"][0]["url"] == f"{PUBLIC}/{keys[0]}"
    body, content_type = s3.objects[keys[0]]
    assert content_type == "image/webp"
    assert Image.open(io.BytesIO(body)).size == (1600, 800)

    # 목록 조회와 행사 상세에도 같은 형식으로 내려간다.
    assert client.get("/api/reviews/my", headers=headers).json["data"][0]["images"][0]["key"] == keys[0]
    assert client.get(f"/api/events/{eid}", headers=headers).json["data"]["reviews"][0]["images"][1]["key"] == keys[1]


def test_json_review_without_images_still_works(client, login, make_event, s3):
    headers, _, _ = login()
    response = client.post("/api/reviews", headers=headers, json={"event_id": make_event().id, "rating": 5, "content": "글만"})
    assert response.status_code == 201
    assert response.json["data"]["images"] == []


def test_create_rejects_bad_images_without_storing(client, login, make_event, s3, monkeypatch):
    """하나라도 잘못된 사진이 섞이면 리뷰도 사진도 남지 않는다."""
    headers, _, _ = login()
    eid = make_event().id

    response = _post(client, headers, eid, _files(1) + [(io.BytesIO(b"<?php echo 1; ?>"), "x.jpg")])
    assert (response.status_code, response.json["code"]) == (400, "REVIEW_IMAGE_INVALID")

    response = _post(client, headers, eid, _files(6))
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")

    monkeypatch.setattr(images, "MAX_UPLOAD_BYTES", 100)
    response = _post(client, headers, eid)
    assert (response.status_code, response.json["code"]) == (413, "REVIEW_IMAGE_TOO_LARGE")

    assert s3.objects == {}
    assert db.session.query(Review).count() == 0


def test_create_rejects_client_supplied_keys(client, login, make_event, s3):
    """작성 시 key는 받지 않는다. 사진은 파일로만 붙는다."""
    headers, _, _ = login()
    response = client.post("/api/reviews", headers=headers, json={
        "event_id": make_event().id, "rating": 5, "content": "x", "images": ["reviews/" + "a" * 32 + ".webp"],
    })
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")


def test_failed_create_deletes_stored_images(client, login, make_event, s3):
    """사진은 올라갔는데 리뷰 저장이 거절되면(이미 쓴 행사) 올린 사진을 지운다."""
    headers, _, _ = login()
    eid = make_event().id
    first = _keys(_post(client, headers, eid))

    response = _post(client, headers, eid, _files(2))
    assert (response.status_code, response.json["code"]) == (409, "REVIEW_ALREADY_EXISTS")
    assert set(s3.objects) == set(first)


def test_storage_failure_midway_deletes_already_stored(client, login, make_event, s3, monkeypatch):
    headers, _, _ = login()
    put = s3.put_object
    calls = []

    def flaky(**kwargs):
        calls.append(1)
        if len(calls) == 2:
            from botocore.exceptions import BotoCoreError
            raise BotoCoreError()
        put(**kwargs)

    monkeypatch.setattr(s3, "put_object", flaky)
    response = _post(client, headers, make_event().id, _files(3))
    assert (response.status_code, response.json["code"]) == (503, "REVIEW_IMAGE_STORAGE_UNAVAILABLE")
    assert s3.objects == {}


def test_without_storage_config_is_503(client, login, make_event, app, monkeypatch):
    for key in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.setitem(app.config, key, None)
    headers, _, _ = login()
    response = _post(client, headers, make_event().id)
    assert (response.status_code, response.json["code"]) == (503, "REVIEW_IMAGE_STORAGE_UNAVAILABLE")


def test_update_keeps_removes_and_adds_images(client, login, make_event, s3):
    headers, _, _ = login()
    rid_response = _post(client, headers, make_event().id, _files(2))
    rid = rid_response.json["data"]["id"]
    k1, k2 = _keys(rid_response)

    # k2만 남기고 새 사진 하나 추가. 빠진 k1은 저장소에서도 지운다.
    updated = _put(client, headers, rid, _files(1), images=[k2])
    assert updated.status_code == 200
    k2_, k3 = _keys(updated)
    assert k2_ == k2 and k1 not in s3.objects and k3 in s3.objects

    # 새 사진만 보내면 기존 사진 뒤에 붙는다.
    assert len(_keys(_put(client, headers, rid, _files(1)))) == 3

    # images 없이 내용만 수정하면 사진은 그대로다.
    kept = client.put(f"/api/reviews/{rid}", headers=headers, json={"content": "내용만 수정"})
    assert len(_keys(kept)) == 3

    # 빈 목록이면 모두 지운다.
    cleared = client.put(f"/api/reviews/{rid}", headers=headers, json={"images": []})
    assert _keys(cleared) == [] and s3.objects == {}


def test_update_rejects_keys_not_in_review_and_too_many(client, login, make_event, s3):
    """남의 리뷰 key를 남길 목록에 넣어 가져올 수 없고, 합계 5장을 넘길 수 없다."""
    a, _, _ = login(kakao_id=8001)
    b, _, _ = login(kakao_id=8002)
    a_key = _keys(_post(client, a, make_event().id))[0]
    b_rid = _post(client, b, make_event().id).json["data"]["id"]

    response = _put(client, b, b_rid, content="바뀜", images=[a_key])
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")
    db.session.expire_all()
    assert db.session.get(Review, b_rid).content == "후기"

    response = _put(client, b, b_rid, _files(5))
    assert (response.status_code, response.json["code"]) == (400, "COMMON_INVALID_INPUT")
    assert len(s3.objects) == 2


def test_delete_review_deletes_images(client, login, make_event, s3):
    headers, _, _ = login()
    response = _post(client, headers, make_event().id, _files(2))
    assert client.delete(f"/api/reviews/{response.json['data']['id']}", headers=headers).status_code == 200
    assert s3.objects == {}


def test_shared_key_survives_delete_and_withdraw(client, login, make_event, s3, monkeypatch):
    """예전 데이터처럼 두 리뷰가 같은 key를 쓰면 한쪽을 지우거나 탈퇴해도 파일은 남는다."""
    from app.domains.auth import kakao_client

    monkeypatch.setattr(kakao_client, "unlink_kakao_user", lambda kakao_id: None)
    a, _, _ = login(kakao_id=8101)
    b, _, _ = login(kakao_id=8102)
    shared, own = _keys(_post(client, a, make_event().id, _files(2)))
    b1 = _post(client, b, make_event().id, []).json["data"]["id"]
    b2 = _post(client, b, make_event().id, []).json["data"]["id"]
    # API로는 만들 수 없는 공유 상태를 DB에 직접 만든다
    db.session.get(Review, b1).images = [shared]
    db.session.get(Review, b2).images = [shared]
    db.session.commit()

    assert client.delete(f"/api/reviews/{b1}", headers=b).status_code == 200
    assert shared in s3.objects

    assert client.delete("/api/users/me", headers=a).status_code == 200
    assert own not in s3.objects
    assert shared in s3.objects


def test_request_body_over_limit_is_413(client, login, app, make_event, s3):
    headers, _, _ = login()
    big = [(io.BytesIO(b"0" * (app.config["MAX_CONTENT_LENGTH"] + 1)), "big.jpg")]
    response = _post(client, headers, make_event().id, big)
    # FE errors.ts가 이 코드로 "파일 크기를 줄여 주세요" 문구를 고른다
    assert (response.status_code, response.json["code"]) == (413, "COMMON_PAYLOAD_TOO_LARGE")


def test_review_read_without_storage_config_returns_null_url(client, login, make_event, s3, app, monkeypatch):
    """저장소 설정이 빠져도 리뷰 조회는 200이고 url만 null이다."""
    headers, _, _ = login()
    eid = make_event().id
    key = _keys(_post(client, headers, eid))[0]
    for name in ("S3_PUBLIC_URL", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
        monkeypatch.setitem(app.config, name, None)

    response = client.get(f"/api/reviews/event/{eid}", headers=headers)
    assert response.status_code == 200
    assert response.json["data"][0]["images"] == [{"key": key, "url": None}]
