"""리뷰 content 검증, 행사 목록 공백 검색어 JWT 정책, 타임스탬프 UTC 표기 통합 테스트."""
from datetime import datetime

import pytest


def err(resp, status, code):
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is False and body["code"] == code


def post_review(client, headers, event_id, content="좋아요"):
    return client.post("/api/reviews", headers=headers,
                       json={"event_id": event_id, "rating": 4.0, "content": content})


@pytest.mark.parametrize("content", ["   ", "\n\t", "x" * 1001, ""])
def test_create_review_invalid_content_400(client, refs, make_event, login, content):
    h, _, _ = login()
    ev = make_event()
    err(post_review(client, h, ev.id, content), 400, "COMMON_INVALID_INPUT")


def test_create_review_max_length_ok_and_stripped(client, refs, make_event, login):
    h, _, _ = login()
    ev = make_event()
    assert post_review(client, h, ev.id, "x" * 1000).status_code == 201
    ev2 = make_event()
    resp = post_review(client, h, ev2.id, "  hi  ")
    assert resp.status_code == 201
    assert resp.get_json()["data"]["content"] == "hi"


@pytest.mark.parametrize("content", ["   ", "x" * 1001])
def test_update_review_invalid_content_400(client, refs, make_event, login, content):
    h, _, _ = login()
    ev = make_event()
    rid = post_review(client, h, ev.id).get_json()["data"]["id"]
    err(client.put(f"/api/reviews/{rid}", headers=h, json={"content": content}), 400, "COMMON_INVALID_INPUT")


def test_update_review_max_length_ok(client, refs, make_event, login):
    h, _, _ = login()
    ev = make_event()
    rid = post_review(client, h, ev.id).get_json()["data"]["id"]
    resp = client.put(f"/api/reviews/{rid}", headers=h, json={"content": "가" * 1000})
    assert resp.status_code == 200


@pytest.mark.parametrize("qs", ["q=%20", "q=+&tag=%20%20"])
def test_blank_search_params_do_not_require_jwt(client, refs, qs):
    assert client.get(f"/api/events?{qs}").status_code == 200


@pytest.mark.parametrize("qs", ["q=%20x", "q=a"])
def test_non_blank_search_requires_jwt(client, refs, qs):
    err(client.get(f"/api/events?{qs}"), 401, "AUTH_UNAUTHORIZED")


def test_review_timestamps_have_utc_marker(client, refs, make_event, login):
    h, _, _ = login()
    ev = make_event()
    post_review(client, h, ev.id)
    detail = client.get(f"/api/events/{ev.id}", headers=h).get_json()["data"]["reviews"][0]
    mine = client.get("/api/reviews/my", headers=h).get_json()["data"][0]
    for r in (detail, mine):
        for key in ("created_at", "updated_at"):
            assert r[key].endswith("+00:00")
            assert datetime.fromisoformat(r[key]).tzinfo is not None
