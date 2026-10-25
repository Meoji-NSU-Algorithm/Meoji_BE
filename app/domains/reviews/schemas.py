"""리뷰 API의 요청 검증 스키마와 응답 직렬화 스키마."""

from marshmallow import (
    Schema,
    fields,
    validate,
    validates_schema,
    ValidationError,
)


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

    content = fields.String(required=True, validate=validate.Length(min=1))


class ReviewUpdateSchema(Schema):
    """리뷰 수정 요청 본문. 보낸 필드만 수정하며 하나 이상 있어야 한다."""

    rating = fields.Float(required=False, validate=validate_rating)

    content = fields.String(required=False, validate=validate.Length(min=1))

    @validates_schema
    def validate_update(self, data, **kwargs):
        if not data:
            raise ValidationError("수정할 값이 없습니다.")


class ReviewResponseSchema(Schema):
    """Review 한 건의 응답 형식."""

    id = fields.Integer()
    user_id = fields.Integer()
    event_id = fields.Integer()
    rating = fields.Float()
    content = fields.String()
    created_at = fields.DateTime()
    updated_at = fields.DateTime()


class EventRatingResponseSchema(Schema):
    """행사의 평균 평점 응답. 리뷰가 없으면 average_rating과 review_count가 0이다."""

    event_id = fields.Integer()
    average_rating = fields.Float()
    review_count = fields.Integer()
