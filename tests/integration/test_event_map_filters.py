"""지도용 행사 목록 조건(has_coords, 지도 영역)과 카드 tags 테스트. (#45)"""
import pytest
from sqlalchemy import event as sa_event

from app.core.extensions import db

BOUNDS = "min_lat=36.7&max_lat=36.9&min_lng=127.0&max_lng=127.3"


def ids(client, qs, headers=None):
    response = client.get(f"/api/events?{qs}", headers=headers or {})
    assert response.status_code == 200, response.get_json()
    return sorted(e["id"] for e in response.get_json()["data"]["events"])


def test_has_coords_filters_out_events_without_location(client, make_event):
    with_coords = make_event(latitude=36.8, longitude=127.1)
    make_event(latitude=None, longitude=None)
    make_event(latitude=36.8, longitude=None)
    assert ids(client, "has_coords=true") == [with_coords.id]
    assert len(ids(client, "has_coords=false")) == 3  # false면 거르지 않는다


def test_bounds_returns_only_events_inside(client, make_event):
    inside = make_event(latitude=36.8, longitude=127.1)
    edge = make_event(latitude=36.9, longitude=127.3)  # 경계 포함
    make_event(latitude=37.5, longitude=127.0)  # 서울, 영역 밖
    make_event(latitude=36.8, longitude=126.9)  # 경도만 밖
    make_event(latitude=None, longitude=None)
    assert ids(client, BOUNDS) == sorted([inside.id, edge.id])


def test_map_params_do_not_require_login(client, make_event):
    make_event(latitude=36.8, longitude=127.1)
    assert len(ids(client, f"has_coords=true&{BOUNDS}&size=100")) == 1


def test_bounds_combine_with_other_filters(client, login, make_event, refs):
    headers, _, _ = login(kakao_id=4501)
    target = make_event(latitude=36.8, longitude=127.1, category=refs["cats"][1])
    make_event(latitude=36.8, longitude=127.1, category=refs["cats"][0])
    assert ids(client, f"{BOUNDS}&category_id={refs['cats'][1].id}", headers) == [target.id]


@pytest.mark.parametrize("qs, field", [
    ("min_lat=36.7&max_lat=36.9&min_lng=127.0", "max_lng"),  # 네 값 중 하나 빠짐
    ("min_lat=36.9&max_lat=36.7&min_lng=127.0&max_lng=127.3", "max_lat"),  # 뒤집힘
    ("min_lat=36.7&max_lat=36.9&min_lng=127.3&max_lng=127.0", "max_lng"),
    ("min_lat=-91&max_lat=36.9&min_lng=127.0&max_lng=127.3", "min_lat"),  # 범위 밖
    ("min_lat=36.7&max_lat=36.9&min_lng=127.0&max_lng=181", "max_lng"),
    ("min_lat=nan&max_lat=36.9&min_lng=127.0&max_lng=127.3", "min_lat"),
    ("min_lat=abc&max_lat=36.9&min_lng=127.0&max_lng=127.3", "min_lat"),
    ("has_coords=yes", "has_coords"),
])
def test_invalid_map_params_400(client, qs, field):
    response = client.get(f"/api/events?{qs}")
    body = response.get_json()
    assert response.status_code == 400 and body["code"] == "COMMON_INVALID_INPUT"
    assert field in body["errors"]


def test_cards_include_sorted_tags(client, make_event, make_tag, login):
    b, a = make_tag("야간"), make_tag("가족")
    tagged = make_event(tags=(b, a))
    plain = make_event()
    cards = {c["id"]: c for c in client.get("/api/events").get_json()["data"]["events"]}
    assert cards[tagged.id]["tags"] == ["가족", "야간"]
    assert cards[plain.id]["tags"] == []
    top = client.get("/api/events/monthly-top").get_json()["data"]["events"]
    assert {c["id"]: c["tags"] for c in top}[tagged.id] == ["가족", "야간"]
    headers, _, _ = login(kakao_id=4511)
    detail = client.get(f"/api/events/{tagged.id}", headers=headers).get_json()["data"]
    assert detail["tags"] == ["가족", "야간"]


@pytest.mark.parametrize("url", ["/api/events", "/api/events/monthly-top?size=6"])
def test_tag_query_does_not_grow_with_cards(client, make_event, make_tag, url):
    """카드 수와 상관없이 태그 조회는 한 번(selectinload)이다."""
    tags = [make_tag(f"태그{i}") for i in range(3)]
    for i in range(6):
        make_event(tags=tags[: i % 3 + 1])

    tag_queries = []

    def count(conn, cursor, statement, *args):
        if "FROM tags" in statement or "JOIN tags" in statement:
            tag_queries.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", count)
    try:
        response = client.get(url)
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert len(response.get_json()["data"]["events"]) == 6
    assert len(tag_queries) == 1
