"""리뷰 작성자 공개 정보 응답 검증."""
from app.core.extensions import db
from app.domains.users.models import User


def test_review_author_fields(client, login, make_event):
    eid = make_event().id
    author_headers, _, uid = login(kakao_id=7001, nickname="작성자")
    viewer_headers, _, _ = login(kakao_id=7002)
    user = db.session.get(User, uid)
    user.profile_image = "https://example.com/profile.jpg"
    db.session.commit()
    expected_author = {"id": uid, "nickname": "작성자", "profile_image": user.profile_image}
    created = client.post("/api/reviews", headers=author_headers, json={"event_id": eid, "rating": 4.5, "content": "후기"})
    assert created.status_code == 201
    assert created.json["data"]["author"] == expected_author
    assert created.json["data"]["images"] == []
    for path, headers in [(f"/api/reviews/event/{eid}", viewer_headers), ("/api/reviews/my", author_headers)]:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        assert response.json["data"][0]["author"] == expected_author
    detail = client.get(f"/api/events/{eid}", headers=viewer_headers).json["data"]
    assert detail["reviews"][0]["author"] == expected_author


def test_review_list_loads_authors_in_one_query(client, login, make_event, app):
    """relationship 없이 작성자를 채워도 리뷰 수만큼 사용자 조회가 늘지 않는다."""
    from sqlalchemy import event as sa_event

    eid = make_event().id
    viewer_headers, _, _ = login(kakao_id=7100)
    for n in range(5):
        headers, _, _ = login(kakao_id=7101 + n, nickname=f"작성자{n}")
        client.post("/api/reviews", headers=headers, json={"event_id": eid, "rating": 4, "content": "후기"})

    user_queries = []

    def count(conn, cursor, statement, *args):
        if "FROM user" in statement:
            user_queries.append(statement)

    sa_event.listen(db.engine, "before_cursor_execute", count)
    try:
        response = client.get(f"/api/reviews/event/{eid}", headers=viewer_headers)
    finally:
        sa_event.remove(db.engine, "before_cursor_execute", count)

    assert response.status_code == 200
    assert {r["author"]["nickname"] for r in response.json["data"]} == {f"작성자{n}" for n in range(5)}
    assert len(user_queries) == 1
