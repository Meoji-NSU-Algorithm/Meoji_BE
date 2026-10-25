"""행사 조회와 리뷰 작성/수정/삭제 전체 흐름 HTTP 통합 테스트."""
from datetime import timedelta, datetime

import pytest

from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Event, EventDailyView


def err(resp, status, code):
    """에러 envelope을 확인한다."""
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is False and body["code"] == code
    return body


def post_review(client, headers, event_id, rating=4.0, content="좋아요"):
    return client.post("/api/reviews", headers=headers,
                       json={"event_id": event_id, "rating": rating, "content": content})


# ---------- events ----------

def test_options_endpoints(client, refs):
    """카테고리/시도 선택지가 sort_order 순으로 내려온다."""
    cats = client.get("/api/events/categories").get_json()
    assert cats["success"] is True
    assert [c["name"] for c in cats["data"]] == ["축제", "공연"]
    assert set(cats["data"][0]) == {"id", "name", "sort_order"}
    sidos = client.get("/api/events/sidos").get_json()["data"]
    assert [s["code"] for s in sidos] == ["44", "11"]
    assert set(sidos[0]) == {"code", "name", "short_name", "sort_order"}
    assert client.get("/api/events/categories?x=1").status_code == 400


def test_list_filters_and_pagination(client, refs, make_event, make_tag):
    """목록 필터, 페이지네이션, 범위 밖 페이지."""
    tag = make_tag("야시장")
    a = make_event(title="벚꽃축제", tags=[tag], is_free=True)
    b = make_event(title="재즈공연", category=refs["cats"][1], sido=refs["sidos"][1], is_free=False, price=5000)
    make_event(title="지난행사", end_date=datetime.now(KST).date() - timedelta(days=1),
               start_date=datetime.now(KST).date() - timedelta(days=5))

    data = client.get("/api/events").get_json()["data"]
    assert data["total_count"] == 2 and data["page"] == 1 and data["size"] == 20
    assert {e["id"] for e in data["events"]} == {a.id, b.id}
    card = next(e for e in data["events"] if e["id"] == a.id)
    assert card["category"] == "축제" and card["sido"] == "충남"

    def ids(qs):
        return [e["id"] for e in client.get(f"/api/events?{qs}").get_json()["data"]["events"]]

    assert ids("q=벚꽃") == [a.id]
    assert ids("tag=야시장") == [a.id]
    assert ids(f"category_id={refs['cats'][1].id}") == [b.id]
    assert ids("sido_code=11") == [b.id]
    assert ids("is_free=true") == [a.id]
    assert ids("is_free=false") == [b.id]
    assert ids("q=없는검색어") == []

    page1 = client.get("/api/events?size=1&page=1").get_json()["data"]
    assert len(page1["events"]) == 1 and page1["total_count"] == 2
    past = client.get("/api/events?size=1&page=5")
    assert past.status_code == 200
    d = past.get_json()["data"]
    assert d["events"] == [] and d["total_count"] == 2 and d["page"] == 5


@pytest.mark.parametrize("qs", ["page=0", "size=101", "sort=bogus", "start_date=2026-1-1",
                                "is_free=yes", "sido_code=4", "page=abc",
                                "start_date=2026-02-02&end_date=2026-01-01", "page=1&page=2"])
def test_list_invalid_query_returns_400(client, qs):
    """잘못된 쿼리는 400 COMMON_INVALID_INPUT."""
    err(client.get(f"/api/events?{qs}"), 400, "COMMON_INVALID_INPUT")


def test_monthly_top(client, refs, make_event):
    """월간 인기: 조회 기록이 많은 순, 잘못된 month는 400."""
    a, b = make_event(), make_event()
    today = datetime.now(KST).date()
    db.session.add_all([EventDailyView(event_id=a.id, view_date=today, view_count=1),
                        EventDailyView(event_id=b.id, view_date=today, view_count=9)])
    db.session.commit()
    data = client.get("/api/events/monthly-top").get_json()["data"]
    assert data["month"] == today.strftime("%Y-%m")
    assert data["events"][0]["id"] == b.id and data["events"][0]["monthly_views"] == 9
    assert client.get("/api/events/monthly-top?month=2020-01").status_code == 200
    err(client.get("/api/events/monthly-top?month=2026-9"), 400, "COMMON_INVALID_INPUT")
    err(client.get("/api/events/monthly-top?size=0"), 400, "COMMON_INVALID_INPUT")


def test_event_detail_and_view_count(client, refs, make_event):
    """상세 조회마다 view_count가 오르고 DB에 반영된다."""
    event = make_event(title="상세행사", description="설명")
    eid = event.id
    first = client.get(f"/api/events/{eid}")
    assert first.status_code == 200
    data = first.get_json()["data"]
    assert data["id"] == eid and data["title"] == "상세행사" and data["description"] == "설명"
    assert data["reviews"] == [] and data["review_count"] == 0 and data["average_rating"] == 0
    client.get(f"/api/events/{eid}")
    db.session.remove()  # REPEATABLE READ 스냅샷을 버리고 새로 읽는다
    assert db.session.get(Event, eid).view_count == 2
    today = datetime.now(KST).date()
    assert db.session.get(EventDailyView, (eid, today)).view_count == 2


@pytest.mark.parametrize("path,status,code", [
    ("/api/events/0", 400, "COMMON_INVALID_INPUT"),
    ("/api/events/abc", 404, "COMMON_NOT_FOUND"),
    ("/api/events/-1", 404, "COMMON_NOT_FOUND"),
    ("/api/events/99999999999", 400, "COMMON_INVALID_INPUT"),
    ("/api/events/999999", 404, "EVENT_NOT_FOUND"),
    ("/api/event", 404, "COMMON_NOT_FOUND"),
    ("/api/event/1", 404, "COMMON_NOT_FOUND"),
])
def test_event_detail_invalid_ids(client, refs, path, status, code):
    """잘못된 id와 옛 경로는 envelope 에러."""
    err(client.get(path), status, code)


# ---------- reviews ----------

def test_review_journey(client, refs, make_event, login):
    """리뷰 작성 후 상세/목록/평점/내 리뷰에 반영된다."""
    event = make_event()
    eid = event.id
    h1, _, u1 = login(kakao_id=1)
    h2, _, u2 = login(kakao_id=2)

    resp = post_review(client, h1, eid, 4.5, "첫 리뷰")
    assert resp.status_code == 201
    r1 = resp.get_json()["data"]
    assert r1["user_id"] == u1 and r1["event_id"] == eid and r1["rating"] == 4.5
    assert set(r1) == {"id", "user_id", "event_id", "rating", "content", "created_at", "updated_at"}
    r2 = post_review(client, h2, eid, 3.0, "둘째").get_json()["data"]

    detail = client.get(f"/api/events/{eid}").get_json()["data"]
    assert detail["review_count"] == 2 and detail["average_rating"] == 3.8
    assert {r["id"] for r in detail["reviews"]} == {r1["id"], r2["id"]}

    # 행사별 목록/평점: JWT 필요
    listed = client.get(f"/api/reviews/event/{eid}", headers=h1)
    assert listed.status_code == 200
    assert [r["id"] for r in listed.get_json()["data"]] == [r2["id"], r1["id"]]
    rating = client.get(f"/api/reviews/event/{eid}/rating", headers=h1).get_json()["data"]
    assert rating == {"event_id": eid, "average_rating": 3.8, "review_count": 2}


def test_review_endpoints_unknown_event_returns_empty(client, refs, login):
    """없는 행사의 리뷰 목록/평점은 404가 아니라 200 빈 목록/0점이다."""
    h, _, _ = login()
    listed = client.get("/api/reviews/event/9999", headers=h)
    assert listed.status_code == 200 and listed.get_json()["data"] == []
    rating = client.get("/api/reviews/event/9999/rating", headers=h)
    assert rating.status_code == 200
    assert rating.get_json()["data"] == {"event_id": 9999, "average_rating": 0.0, "review_count": 0}


def test_event_review_endpoints_require_jwt(client, refs, make_event):
    """행사별 리뷰 목록/평점은 JWT가 없으면 401이다."""
    eid = make_event().id
    err(client.get(f"/api/reviews/event/{eid}"), 401, "AUTH_UNAUTHORIZED")
    err(client.get(f"/api/reviews/event/{eid}/rating"), 401, "AUTH_UNAUTHORIZED")


def test_create_review_unknown_event_404(client, refs, login):
    """없는 행사에 리뷰를 쓰면 404 EVENT_NOT_FOUND."""
    h, _, _ = login()
    err(post_review(client, h, 9999), 404, "EVENT_NOT_FOUND")


def test_create_review_requires_auth(client, refs, make_event):
    """리뷰 작성은 JWT가 필요하다."""
    event = make_event()
    resp = client.post("/api/reviews", json={"event_id": event.id, "rating": 4, "content": "x"})
    err(resp, 401, "AUTH_UNAUTHORIZED")


def test_my_reviews_requires_jwt_and_lists_only_mine_newest_first(client, refs, make_event, login):
    """내 리뷰는 JWT 필수이며 본인 것만 최신순으로 보인다."""
    err(client.get("/api/reviews/my"), 401, "AUTH_UNAUTHORIZED")
    e1, e2 = make_event(), make_event()
    h1, _, _ = login(kakao_id=1)
    h2, _, _ = login(kakao_id=2)
    a = post_review(client, h1, e1.id, 4, "a").get_json()["data"]
    b = post_review(client, h1, e2.id, 5, "b").get_json()["data"]
    post_review(client, h2, e1.id, 1, "other")
    mine = client.get("/api/reviews/my", headers=h1).get_json()["data"]
    assert [r["id"] for r in mine] == [b["id"], a["id"]]
    assert client.get("/api/reviews/my", headers=h2).get_json()["data"][0]["content"] == "other"


def test_other_user_cannot_update_or_delete(client, refs, make_event, login):
    """남의 리뷰 수정/삭제는 403 REVIEW_FORBIDDEN, 없는 리뷰는 404."""
    event = make_event()
    h1, _, _ = login(kakao_id=1)
    h2, _, _ = login(kakao_id=2)
    rid = post_review(client, h1, event.id).get_json()["data"]["id"]
    err(client.put(f"/api/reviews/{rid}", headers=h2, json={"content": "hack"}), 403, "REVIEW_FORBIDDEN")
    err(client.delete(f"/api/reviews/{rid}", headers=h2), 403, "REVIEW_FORBIDDEN")
    err(client.put("/api/reviews/9999", headers=h1, json={"content": "x"}), 404, "REVIEW_NOT_FOUND")
    err(client.delete("/api/reviews/9999", headers=h1), 404, "REVIEW_NOT_FOUND")
    assert client.get("/api/reviews/my", headers=h1).get_json()["data"][0]["content"] == "좋아요"


def test_owner_partial_update_and_delete(client, refs, make_event, login):
    """작성자는 일부 필드만 수정하고 삭제할 수 있다."""
    event = make_event()
    eid = event.id
    h, _, _ = login()
    rid = post_review(client, h, eid, 4.0, "원본").get_json()["data"]["id"]

    r = client.put(f"/api/reviews/{rid}", headers=h, json={"rating": 2.5}).get_json()["data"]
    assert r["rating"] == 2.5 and r["content"] == "원본"
    r = client.put(f"/api/reviews/{rid}", headers=h, json={"content": "수정"}).get_json()["data"]
    assert r["rating"] == 2.5 and r["content"] == "수정"
    assert client.get(f"/api/reviews/event/{eid}/rating", headers=h).get_json()["data"]["average_rating"] == 2.5

    deleted = client.delete(f"/api/reviews/{rid}", headers=h)
    assert deleted.status_code == 200 and deleted.get_json()["data"]["id"] == rid
    assert client.get(f"/api/reviews/event/{eid}", headers=h).get_json()["data"] == []
    assert client.get(f"/api/reviews/event/{eid}/rating", headers=h).get_json()["data"]["review_count"] == 0
    err(client.delete(f"/api/reviews/{rid}", headers=h), 404, "REVIEW_NOT_FOUND")


@pytest.mark.parametrize("rating", [0.3, 0, 5.5, -1, "abc", None, 4.25])
def test_invalid_rating_returns_400(client, refs, make_event, login, rating):
    """잘못된 평점은 작성/수정 모두 400 COMMON_INVALID_INPUT."""
    event = make_event()
    h, _, _ = login()
    body = err(post_review(client, h, event.id, rating), 400, "COMMON_INVALID_INPUT")
    assert "rating" in body["errors"]
    rid = post_review(client, h, event.id, 4).get_json()["data"]["id"]
    err(client.put(f"/api/reviews/{rid}", headers=h, json={"rating": rating}), 400, "COMMON_INVALID_INPUT")


@pytest.mark.parametrize("payload", [
    {"rating": 4, "content": "x"},
    {"event_id": 1.5, "rating": 4, "content": "x"},
    {"event_id": "1", "rating": 4, "content": "x"},
    {"event_id": 0, "rating": 4, "content": "x"},
    {"event_id": 1, "rating": 4, "content": ""},
    {"event_id": 1, "rating": 4},
])
def test_invalid_create_body_returns_400(client, refs, login, payload):
    """작성 본문 검증 실패는 400."""
    h, _, _ = login()
    err(client.post("/api/reviews", headers=h, json=payload), 400, "COMMON_INVALID_INPUT")


def test_empty_update_body_returns_400(client, refs, make_event, login):
    """수정 본문이 비어 있으면 400."""
    event = make_event()
    h, _, _ = login()
    rid = post_review(client, h, event.id).get_json()["data"]["id"]
    err(client.put(f"/api/reviews/{rid}", headers=h, json={}), 400, "COMMON_INVALID_INPUT")
    err(client.put(f"/api/reviews/{rid}", headers=h), 400, "COMMON_INVALID_INPUT")
