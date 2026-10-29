"""리뷰 API의 요청 검증 스키마와 응답 직렬화 스키마."""

from marshmallow import (
    Schema,
    fields,
    pre_load,
    validate,
    validates_schema,
    ValidationError,
)

from app.core.fields import UtcDateTime

CONTENT_MAX_LENGTH = 1000
CONTENT_LENGTH_MESSAGE = "리뷰 내용은 공백을 제외하고 1~1000자여야 합니다."


def _content_validator():
    """content 필드용 길이 검증기를 만든다. 글자 수 기준이며 바이트 수가 아니다."""
    return validate.Length(min=1, max=CONTENT_MAX_LENGTH, error=CONTENT_LENGTH_MESSAGE)


def _strip_content(data):
    """content가 문자열이면 앞뒤 공백을 제거한 사본을 돌려준다. 문자열이 아니면 String 필드가 거부하도록 그대로 둔다."""
    if isinstance(data, dict) and isinstance(data.get("content"), str):
        data = {**data, "content": data["content"].strip()}
    return data


def validate_rating(value):
    """평점이 0.5~5.0 범위의 0.5 단위인지 검증한다. rating 필드의 validate로 쓴다."""
    if value < 0.5 or value > 5:
        raise ValidationError("평점은 0.5 단위로 0.5~5.0 사이여야 합니다.")

    if value * 2 != int(value * 2):
        raise ValidationError("평점은 0.5 단위로 0.5~5.0 사이여야 합니다.")


class ReviewCreateSchema(Schema):
    """리뷰 작성 요청 본문."""

    event_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))

    rating = fields.Float(required=True, validate=validate_rating)

    content = fields.String(required=True, validate=_content_validator())

    @pre_load
    def strip_content(self, data, **kwargs):
        # 공백만 있는 리뷰를 길이 검증으로 걸러내기 위해 검증 전에 제거한다.
        return _strip_content(data)


class ReviewUpdateSchema(Schema):
    """리뷰 수정 요청 본문. 보낸 필드만 수정하며 하나 이상 있어야 한다."""

    rating = fields.Float(required=False, validate=validate_rating)

    content = fields.String(required=False, validate=_content_validator())

    @pre_load
    def strip_content(self, data, **kwargs):
        # 공백만 있는 리뷰를 길이 검증으로 걸러내기 위해 검증 전에 제거한다.
        return _strip_content(data)

    @validates_schema
    def validate_update(self, data, **kwargs):
        if not data:
            raise ValidationError("수정할 값이 없습니다.")


class ReviewEventResponseSchema(Schema):
    """리뷰에 포함할 행사 정보."""
    id = fields.Integer()
    title = fields.String()
    image_url = fields.String(allow_none=True)
    end_date = fields.Date()


class ReviewResponseSchema(Schema):
    """Review 한 건의 응답 형식."""

    id = fields.Integer()
    user_id = fields.Integer()
    event_id = fields.Integer()
    rating = fields.Float()
    content = fields.String()
    created_at = UtcDateTime()
    updated_at = UtcDateTime()
    event = fields.Nested(ReviewEventResponseSchema)


class EventRatingResponseSchema(Schema):
    """행사의 평균 평점 응답. 리뷰가 없으면 average_rating과 review_count가 0이다."""

    event_id = fields.Integer()
    average_rating = fields.Float()
    review_count = fields.Integer()
