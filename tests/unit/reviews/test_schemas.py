"""리뷰 요청/응답 스키마 테스트."""
from datetime import datetime
from decimal import Decimal

import pytest
from marshmallow import ValidationError

from app.domains.reviews.schemas import (
    EventRatingResponseSchema, ReviewCreateSchema, ReviewResponseSchema, ReviewUpdateSchema,
)


def valid(**kw):
    d = {"event_id": 1, "rating": 4.5, "content": "좋아요"}
    d.update(kw)
    return d


@pytest.mark.parametrize("r", [0.5 * i for i in range(1, 11)])
def test_create_valid_ratings(r):
    assert ReviewCreateSchema().load(valid(rating=r))["rating"] == r


def test_create_rating_accepts_int_and_numeric_string():
    assert ReviewCreateSchema().load(valid(rating=3))["rating"] == 3.0
    assert ReviewCreateSchema().load(valid(rating="4.5"))["rating"] == 4.5


@pytest.mark.parametrize("r", [0, 0.4, 5.5, 4.3, -1, -0.5, 6, 0.51, "abc", "", None, [], {}, True])
def test_create_invalid_ratings(r):
    with pytest.raises(ValidationError) as e:
        ReviewCreateSchema().load(valid(rating=r))
    assert "rating" in e.value.messages


@pytest.mark.parametrize("r", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_create_rating_nan_inf_rejected_with_validation_error(r):
    with pytest.raises(ValidationError):
        ReviewCreateSchema().load(valid(rating=r))


def test_create_missing_fields():
    with pytest.raises(ValidationError) as e:
        ReviewCreateSchema().load({})
    assert set(e.value.messages) == {"event_id", "rating", "content"}


@pytest.mark.parametrize("c", ["", None, 1, []])
def test_create_invalid_content(c):
    with pytest.raises(ValidationError) as e:
        ReviewCreateSchema().load(valid(content=c))
    assert "content" in e.value.messages


def test_create_whitespace_only_content_is_accepted():
    # 현재 동작: 공백만 있는 내용도 통과한다 (Length(min=1)만 검사).
    assert ReviewCreateSchema().load(valid(content="   "))["content"] == "   "


def test_create_content_max_length_not_limited_by_schema():
    # 스키마에 상한이 없다. 모델은 Text(65535 bytes)이므로 아주 긴 값은 DB 단계에서 문제가 된다.
    ReviewCreateSchema().load(valid(content="a" * 100000))


@pytest.mark.parametrize("eid", [0, -1, "x", None])
def test_create_invalid_event_id(eid):
    with pytest.raises(ValidationError) as e:
        ReviewCreateSchema().load(valid(event_id=eid))
    assert "event_id" in e.value.messages


def test_create_unknown_field_rejected():
    with pytest.raises(ValidationError):
        ReviewCreateSchema().load(valid(user_id=5))


def test_update_empty_body_rejected():
    with pytest.raises(ValidationError) as e:
        ReviewUpdateSchema().load({})
    assert "수정할 값이 없습니다." in str(e.value.messages)


def test_update_partial():
    assert ReviewUpdateSchema().load({"rating": 2.5}) == {"rating": 2.5}
    assert ReviewUpdateSchema().load({"content": "x"}) == {"content": "x"}


@pytest.mark.parametrize("r", [0, 0.4, 5.5, 4.3, -1, "abc", None])
def test_update_invalid_rating(r):
    with pytest.raises(ValidationError) as e:
        ReviewUpdateSchema().load({"rating": r})
    assert "rating" in e.value.messages


def test_update_blank_content():
    with pytest.raises(ValidationError):
        ReviewUpdateSchema().load({"content": ""})


def test_update_unknown_field_only_rejected():
    with pytest.raises(ValidationError):
        ReviewUpdateSchema().load({"user_id": 3})


def test_response_dump_shape_and_types():
    class Obj:
        id = 1
        user_id = 2
        event_id = 3
        rating = Decimal("4.5")
        content = "hi"
        created_at = datetime(2026, 1, 1, 12, 0, 0)
        updated_at = datetime(2026, 1, 2, 12, 0, 0)

    out = ReviewResponseSchema().dump(Obj())
    assert set(out) == {"id", "user_id", "event_id", "rating", "content", "created_at", "updated_at"}
    assert out["rating"] == 4.5 and isinstance(out["rating"], float)
    assert out["created_at"] == "2026-01-01T12:00:00"


def test_event_rating_dump():
    out = EventRatingResponseSchema().dump({"event_id": 1, "average_rating": 4.2, "review_count": 3})
    assert out == {"event_id": 1, "average_rating": 4.2, "review_count": 3}
    out = EventRatingResponseSchema().dump({"event_id": 1, "average_rating": 0, "review_count": 0})
    assert out["average_rating"] == 0.0 and isinstance(out["average_rating"], float)


def test_create_event_id_float_rejected():
    with pytest.raises(ValidationError):
        ReviewCreateSchema().load(valid(event_id=1.5))
