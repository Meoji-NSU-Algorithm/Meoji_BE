"""북마크 요청 검증과 응답 직렬화 스키마."""
from marshmallow import Schema, ValidationError, fields, validate, validates_schema


class BookmarkCreateSchema(Schema):
    """camelCase와 기존 snake_case 행사 ID 입력을 검증한다."""

    event_id = fields.Integer(
        data_key="eventId",
        required=False,
        strict=True,
        validate=validate.Range(min=1, max=2_147_483_647),
    )
    legacy_event_id = fields.Integer(
        data_key="event_id",
        required=False,
        load_only=True,
        strict=True,
        validate=validate.Range(min=1, max=2_147_483_647),
    )

    @validates_schema
    def validate_event_id(self, data, **kwargs):
        # eventId와 event_id 중 정확히 하나만 받는다(둘 다 없거나 둘 다 있으면 거부).
        if ("event_id" in data) == ("legacy_event_id" in data):
            raise ValidationError({"eventId": ["행사 ID를 하나만 입력해주세요."]})


class BookmarkResponseSchema(Schema):
    """북마크 추가·해제 결과 응답. 대상 행사 ID와 현재 북마크 여부를 담는다."""

    event_id = fields.Integer(data_key="eventId", required=True)
    is_bookmarked = fields.Boolean(data_key="isBookmarked", required=True)


class BookmarkEventSchema(Schema):
    """북마크 목록의 행사 카드 한 건."""

    id = fields.Integer(required=True)
    title = fields.String(required=True)
    image_url = fields.String(data_key="imageUrl", allow_none=True)
    start_date = fields.Date(data_key="startDate", required=True)
    end_date = fields.Date(data_key="endDate", required=True)
    price_type = fields.String(
        data_key="priceType",
        required=True,
        validate=validate.OneOf(("FREE", "PAID", "UNKNOWN")),
    )


class BookmarkListResponseSchema(Schema):
    """내 북마크 목록 응답. 전체 개수와 최근 저장 순 행사 목록을 담는다."""

    total_count = fields.Integer(data_key="totalCount", required=True)
    events = fields.List(fields.Nested(BookmarkEventSchema), required=True)
