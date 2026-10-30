"""행사 API의 쿼리·경로 검증 스키마와 응답 직렬화 스키마.

조회 조건 적용과 값 계산은 service가 하고, 여기서는 타입·형식·범위만 다룬다.
"""

import re

from marshmallow import (
    Schema,
    ValidationError,
    fields,
    post_dump,
    pre_load,
    validate,
    validates_schema,
)

from app.domains.reviews.schemas import ReviewResponseSchema


class QuerySchema(Schema):
    """쿼리 문자열용 베이스 스키마. 같은 키가 반복되면 검증 오류로 처리한다."""

    @pre_load
    def normalize_query(self, data, **kwargs):
        if hasattr(data, "getlist"):
            duplicates = {
                key: ["같은 파라미터는 한 번만 입력해주세요."]
                for key in data
                if len(data.getlist(key)) != 1
            }
            if duplicates:
                raise ValidationError(duplicates)
            return data.to_dict()
        return data


class EmptyQuerySchema(QuerySchema):
    """쿼리 파라미터를 받지 않는 API용. 알 수 없는 키는 거부된다."""

    pass


class EventPathSchema(Schema):
    """행사 상세 경로 파라미터."""

    # INT PK 범위를 벗어난 값은 DB 조회 전에 거부한다.
    event_id = fields.Integer(
        required=True, validate=validate.Range(min=1, max=2_147_483_647)
    )


class CategoryOptionSchema(Schema):
    """카테고리 선택지 응답."""

    id = fields.Integer()
    name = fields.String()
    sort_order = fields.Integer()


class SidoOptionSchema(Schema):
    """시도 선택지 응답. code는 앞자리 0을 유지하기 위해 문자열이다."""

    code = fields.String()
    name = fields.String()
    short_name = fields.String()
    sort_order = fields.Integer()


class EventListQuerySchema(QuerySchema):
    """행사 목록 쿼리. 모든 조건은 AND로 결합된다."""

    # q는 제목·장소·태그를 통합 검색하고, title/venue/tag는 해당 필드만 검색한다.
    # 검색어 길이는 DB 조회 전에 100자로 제한한다.
    q = fields.String(load_default=None, validate=validate.Length(max=100))

    title = fields.String(load_default=None, validate=validate.Length(max=100))
    venue = fields.String(load_default=None, validate=validate.Length(max=100))
    # tag는 연결된 tags.name만 검색하며 소개글 전체 검색이 아니다.
    tag = fields.String(load_default=None, validate=validate.Length(max=100))
    category_id = fields.Integer(
        load_default=None,
        validate=validate.Range(min=1, max=2_147_483_647),
    )
    # 두 자리 숫자 문자열(앞자리 0 유지).
    sido_code = fields.String(
        load_default=None,
        validate=validate.Regexp(r"^[0-9]{2}$"),
    )
    is_free = fields.Boolean(load_default=None, truthy={"true"}, falsy={"false"})
    # 기간이 하루라도 겹치는 행사를 조회한다. 한쪽만 보내도 된다.
    start_date = fields.Date(load_default=None)
    end_date = fields.Date(load_default=None)
    sort = fields.String(
        load_default="latest",
        validate=validate.OneOf(("latest", "popular", "dateAsc")),
    )
    # 초대형 OFFSET을 막기 위해 상한을 둔다.
    page = fields.Integer(
        load_default=1,
        validate=validate.Range(min=1, max=2_147_483_647),
    )
    size = fields.Integer(load_default=20, validate=validate.Range(min=1, max=100))

    @pre_load
    def validate_date_format(self, data, **kwargs):
        # fields.Date는 ISO의 다른 표기도 허용하므로 YYYY-MM-DD 형태부터 확인한다.
        errors = {}
        for key in ("start_date", "end_date"):
            if key in data and (
                not isinstance(data[key], str)
                or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", data[key])
            ):
                errors[key] = ["날짜는 YYYY-MM-DD 형식으로 입력해주세요."]
        if errors:
            raise ValidationError(errors)
        return data

    @validates_schema
    def validate_period(self, data, **kwargs):
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        if start_date and end_date and start_date > end_date:
            raise ValidationError(
                {"end_date": ["종료일은 시작일보다 빠를 수 없습니다."]}
            )


class EventCardSchema(Schema):
    """목록 카드 한 건. category/sido는 표시 이름이고 *_id/*_code는 필터 값이다."""

    id = fields.Integer()
    title = fields.String()
    category_id = fields.Integer()
    category = fields.Function(lambda event: event.category.name)
    sido_code = fields.String()
    sido = fields.Function(lambda event: event.sido.short_name)
    start_date = fields.Date()
    end_date = fields.Date()
    venue_name = fields.String(allow_none=True)
    image_url = fields.String(allow_none=True)
    latitude = fields.Float(allow_none=True)
    longitude = fields.Float(allow_none=True)
    view_count = fields.Integer()
    price = fields.Integer(allow_none=True)
    is_free = fields.Boolean(allow_none=True)


class EventListResponseSchema(Schema):
    """행사 목록 응답. total_count는 현재 페이지가 아니라 필터 전체의 건수다."""

    total_count = fields.Integer()
    page = fields.Integer()
    size = fields.Integer()
    events = fields.List(fields.Nested(EventCardSchema))


class MonthlyTopQuerySchema(QuerySchema):
    """월간 인기 행사 쿼리. month를 생략하면 KST 기준 이번 달이다."""

    month = fields.Date(format="%Y-%m", load_default=None)
    size = fields.Integer(load_default=4, validate=validate.Range(min=1, max=20))

    @pre_load
    def validate_month_format(self, data, **kwargs):
        # strptime은 2026-9도 허용하므로 YYYY-MM 형태를 먼저 확인한다.
        # 존재하지 않는 월은 이후 Date 필드가 거부한다.
        month = data.get("month")
        if "month" in data and (
            not isinstance(month, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month)
        ):
            raise ValidationError({"month": ["조회 월은 YYYY-MM 형식으로 입력해주세요."]})
        return data


class MonthlyTopEventSchema(Schema):
    """월간 순위 카드. 행사 카드 필드에 monthly_views를 더해 평탄화한다."""

    event = fields.Nested(EventCardSchema)
    monthly_views = fields.Integer()

    @post_dump
    def flatten_card(self, data, **kwargs):
        return {**data["event"], "monthly_views": data["monthly_views"]}


class MonthlyTopResponseSchema(Schema):
    """월간 인기 행사 응답."""

    month = fields.String()
    events = fields.List(fields.Nested(MonthlyTopEventSchema))


class EventDetailSchema(EventCardSchema):
    """카드 필드에 소개·주소·연락처·좌표 등 상세 필드를 더한 행사 상세."""

    description = fields.String(allow_none=True)
    address = fields.String(allow_none=True)
    address_detail = fields.String(allow_none=True)
    play_time = fields.String(allow_none=True)
    fee_text = fields.String(allow_none=True)
    organizer = fields.String(allow_none=True)
    contact_phone = fields.String(allow_none=True)
    homepage_url = fields.String(allow_none=True)
    is_permanent = fields.Boolean()


class EventDetailResponseSchema(Schema):
    """행사 상세 응답. 행사 필드를 최상위에 두고 리뷰 목록과 평점 요약을 덧붙인다.

    리뷰는 리뷰 API와 같은 ReviewResponseSchema로 직렬화한다.
    """

    event = fields.Nested(EventDetailSchema)
    reviews = fields.List(fields.Nested(ReviewResponseSchema))
    review_count = fields.Integer()
    average_rating = fields.Float()

    @post_dump
    def flatten_event(self, data, **kwargs):
        # 행사 필드를 data 최상위에 유지하기 위해 event 묶음만 풀어 리뷰 필드와 합친다.
        event = data.pop("event")
        return {**event, **data}
