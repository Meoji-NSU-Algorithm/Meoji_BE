"""행사 목록·월간 인기 카드의 평균 평점과 리뷰 개수 테스트. (#37)"""
from sqlalchemy import event as sa_event

from app.core.extensions import db
from tests.integration.test_events_reviews_flow import post_review


def test_event_list_card_has_rating_and_review_count(client, login, make_event):
    first, _, _ = login(kakao_id=4001)
    second, _, _ = login(kakao_id=4002)
    reviewed = make_event()
    empty = make_event()
    post_review(client, first, reviewed.id, rating=4.0)
    post_review(client, second, reviewed.id, rating=5.0)

    cards = {card["id"]: card for card in client.get("/api/events").get_json()["data"]["events"]}

    assert (cards[reviewed.id]["average_rating"], cards[reviewed.id]["review_count"]) == (4.5, 2)
    assert (cards[empty.id]["average_rating"], cards[empty.id]["review_count"]) == (0, 0)


def test_monthly_top_card_has_rating_and_review_count(client, login, make_event):
    headers, _, _ = login(kakao_id=4011)
    event = make_event()
    post_review(client, headers, event.id, rating=3.5)

    card = client.get("/api/events/monthly-top").get_json()["data"]["events"][0]

    assert (card["id"], card["average_rating"], card["review_count"]) == (event.id, 3.5, 1)


def test_event_list_rating_query_does_not_grow_with_cards(client, login, make_event):
    """카드 수와 상관없이 평점 집계 쿼리는 한 번이다."""
    headers, _, _ = login(kakao_id=4021)
    for _ in range(5):
        make_event()
    post_review(client, headers, make_event().id)

    review_queries = []

    def count(conn, cursor, statement, *args):
        if "FROM review" in statement:
            review_queries.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", count)
    try:
        response = client.get("/api/events")
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert len(response.get_json()["data"]["events"]) == 6
    assert len(review_queries) == 1


def test_event_detail_rating_unchanged(client, login, make_event):
    """상세 응답의 평점 요약은 기존 계산값 그대로다."""
    first, _, _ = login(kakao_id=4031)
    second, _, _ = login(kakao_id=4032)
    event = make_event()
    post_review(client, first, event.id, rating=4.0)
    post_review(client, second, event.id, rating=5.0)

    detail = client.get(f"/api/events/{event.id}", headers=first).get_json()["data"]

    assert (detail["average_rating"], detail["review_count"]) == (4.5, 2)
