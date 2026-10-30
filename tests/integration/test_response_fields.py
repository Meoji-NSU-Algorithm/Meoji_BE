"""행사 응답의 원본 이미지·좌표·조회수 검증."""
from app.core.extensions import db
from app.domains.events.models import Event


def test_event_response_fields(client, login, make_event):
    event = make_event(latitude=36.8, longitude=127.1, image_url="https://example.com/original.jpg")
    eid = event.id
    headers, _, _ = login(kakao_id=7001)
    detail = client.get(f"/api/events/{eid}", headers=headers).json["data"]
    assert detail["view_count"] == 1
    db.session.rollback()  # 상세 조회수는 별도 트랜잭션에서 증가한다.
    for path in ["/api/events", "/api/events/monthly-top"]:
        response = client.get(path)
        assert response.status_code == 200
        card = response.json["data"]["events"][0]
        assert card["latitude"] == 36.8 and card["longitude"] == 127.1
        assert card["view_count"] == 1
        assert card["image_url"] == "https://example.com/original.jpg"
        assert "thumbnail_url" not in card
    assert "thumbnail_url" not in Event.__table__.columns
