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
from app.domains.reviews.images import KEY_PATTERN, MAX_REVIEW_IMAGES, image_url

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


def _images_field():
    """images 필드를 만든다. POST /api/reviews/images가 돌려준 key만 받는다.

    _content_validator()처럼 작성·수정 스키마가 같은 규칙을 쓰도록 함수로 둔다.
    """
    return fields.List(
        fields.String(validate=validate.Regexp(KEY_PATTERN, error="업로드 API가 발급한 이미지 key가 아닙니다.")),
        required=False,
        validate=validate.Length(max=MAX_REVIEW_IMAGES, error=f"이미지는 최대 {MAX_REVIEW_IMAGES}장까지 첨부할 수 있습니다."),
    )


class ReviewCreateSchema(Schema):
    """리뷰 작성 요청 본문."""

    event_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))

    rating = fields.Float(required=True, validate=validate_rating)

    content = fields.String(required=True, validate=_content_validator())

    # 생략하면 이미지 없는 리뷰가 된다.
    images = _images_field()

    @pre_load
    def strip_content(self, data, **kwargs):
        # 공백만 있는 리뷰를 길이 검증으로 걸러내기 위해 검증 전에 제거한다.
        return _strip_content(data)


class ReviewUpdateSchema(Schema):
    """리뷰 수정 요청 본문. 보낸 필드만 수정하며 하나 이상 있어야 한다."""

    rating = fields.Float(required=False, validate=validate_rating)

    content = fields.String(required=False, validate=_content_validator())

    # 보내면 목록 전체를 교체한다. 빈 목록은 이미지를 모두 지운다.
    images = _images_field()

    @pre_load
    def strip_content(self, data, **kwargs):
        # 공백만 있는 리뷰를 길이 검증으로 걸러내기 위해 검증 전에 제거한다.
        return _strip_content(data)

    @validates_schema
    def validate_update(self, data, **kwargs):
        if not data:
            raise ValidationError("수정할 값이 없습니다.")


class ReviewAuthorSchema(Schema):
    """리뷰 작성자의 공개 정보."""

    id = fields.Integer()
    nickname = fields.String()
    profile_image = fields.String(allow_none=True)


class ReviewResponseSchema(Schema):
    """Review 한 건의 응답 형식."""

    author = fields.Nested(ReviewAuthorSchema)
    # [{key, url}]. 수정 요청에는 key를 그대로 돌려보내고, 화면에는 url을 쓴다.
    images = fields.Method("get_images")
    id = fields.Integer()
    user_id = fields.Integer()
    event_id = fields.Integer()
    rating = fields.Float()
    content = fields.String()
    created_at = UtcDateTime()
    updated_at = UtcDateTime()

    def get_images(self, review):
        # 이미지 기능 이전 리뷰(NULL)와 images 속성이 없는 객체는 빈 목록으로 내려준다.
        return [{"key": key, "url": image_url(key)} for key in (getattr(review, "images", None) or [])]


class ReviewImageResponseSchema(Schema):
    """업로드한 이미지 한 장의 응답({key, url}). ReviewResponseSchema.images 항목과 같은 형식이다."""

    key = fields.String()
    url = fields.Function(lambda obj: image_url(obj["key"]))


class EventRatingResponseSchema(Schema):
    """행사의 평균 평점 응답. 리뷰가 없으면 average_rating과 review_count가 0이다."""

    event_id = fields.Integer()
    average_rating = fields.Float()
    review_count = fields.Integer()
