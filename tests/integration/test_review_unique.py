"""사용자당 행사별 리뷰 1개 제약 통합 테스트."""
from tests.integration.test_events_reviews_flow import err, post_review


def test_second_review_same_event_returns_409(client, refs, make_event, login):
    eid = make_event().id
    h, _, _ = login(kakao_id=1)
    assert post_review(client, h, eid).status_code == 201

    body = err(post_review(client, h, eid, 5.0, "또"), 409, "REVIEW_ALREADY_EXISTS")
    assert body["message"] == "이미 이 행사에 리뷰를 작성했습니다."


def test_other_user_can_review_same_event(client, refs, make_event, login):
    eid = make_event().id
    h1, _, _ = login(kakao_id=1)
    h2, _, _ = login(kakao_id=2)
    assert post_review(client, h1, eid).status_code == 201
    assert post_review(client, h2, eid).status_code == 201


def test_can_write_again_after_delete(client, refs, make_event, login):
    eid = make_event().id
    h, _, _ = login(kakao_id=1)
    rid = post_review(client, h, eid).get_json()["data"]["id"]
    assert client.delete(f"/api/reviews/{rid}", headers=h).status_code == 200
    assert post_review(client, h, eid, 3.0, "다시").status_code == 201


def test_event_detail_shows_single_review_after_rejected_duplicate(client, refs, make_event, login):
    eid = make_event().id
    h, _, _ = login(kakao_id=1)
    post_review(client, h, eid)
    post_review(client, h, eid)
    detail = client.get(f"/api/events/{eid}", headers=h).get_json()["data"]
    assert detail["review_count"] == 1 and len(detail["reviews"]) == 1
