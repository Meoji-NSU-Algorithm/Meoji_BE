"""bookmarks 스키마 검증과 응답 직렬화 테스트."""
from datetime import date

import pytest
from marshmallow import ValidationError

from app.domains.bookmarks.schemas import (
    BookmarkCreateSchema,
    BookmarkListResponseSchema,
    BookmarkResponseSchema,
)


def test_create_accepts_camel_case():
    """eventId로 보내면 event_id 키로 읽힌다."""
    assert BookmarkCreateSchema().load({"eventId": 3}) == {"event_id": 3}


def test_create_accepts_legacy_snake_case():
    """기존 event_id 표기는 legacy_event_id 키로 읽힌다."""
    assert BookmarkCreateSchema().load({"event_id": 3}) == {"legacy_event_id": 3}


@pytest.mark.parametrize("body", [
    {}, {"eventId": 1, "event_id": 1},
])
def test_create_requires_exactly_one_id(body):
    """행사 ID가 없거나 두 표기가 함께 오면 거부한다."""
    with pytest.raises(ValidationError):
        BookmarkCreateSchema().load(body)


@pytest.mark.parametrize("value", [0, -1, 1.5, "1", True, None, 2_147_483_648])
@pytest.mark.parametrize("key", ["eventId", "event_id"])
def test_create_rejects_invalid_id(key, value):
    """1 이상 int 최대값 이하의 정수만 허용하고 문자열·불리언·실수는 거부한다."""
    with pytest.raises(ValidationError):
        BookmarkCreateSchema().load({key: value})


def test_create_accepts_boundary_ids():
    assert BookmarkCreateSchema().load({"eventId": 1}) == {"event_id": 1}
    assert BookmarkCreateSchema().load({"eventId": 2_147_483_647}) == {"event_id": 2_147_483_647}


def test_response_uses_camel_case_keys():
    out = BookmarkResponseSchema().dump({"event_id": 7, "is_bookmarked": True})
    assert out == {"eventId": 7, "isBookmarked": True}


def test_list_response_shape_and_price_type():
    out = BookmarkListResponseSchema().dump({
        "total_count": 1,
        "events": [{
            "id": 1, "title": "행사", "image_url": None,
            "start_date": date(2026, 6, 1), "end_date": date(2026, 6, 30), "price_type": "FREE",
        }],
    })
    assert out == {
        "totalCount": 1,
        "events": [{
            "id": 1, "title": "행사", "imageUrl": None,
            "startDate": "2026-06-01", "endDate": "2026-06-30", "priceType": "FREE",
        }],
    }
