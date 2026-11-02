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
        if ("event_id" in data) == ("legacy_event_id" in data):
            raise ValidationError({"eventId": ["행사 ID를 하나만 입력해주세요."]})


class BookmarkResponseSchema(Schema):
    event_id = fields.Integer(data_key="eventId", required=True)
    is_bookmarked = fields.Boolean(data_key="isBookmarked", required=True)


class BookmarkEventSchema(Schema):
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
    total_count = fields.Integer(data_key="totalCount", required=True)
    events = fields.List(fields.Nested(BookmarkEventSchema), required=True)
