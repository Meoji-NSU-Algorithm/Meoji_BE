
"""길찾기 API의 요청 값 검증과 응답 데이터 직렬화를 담당한다."""

from marshmallow import Schema, fields, validate

from app.domains.events.schemas import QuerySchema


class DirectionsQuerySchema(QuerySchema):
    """길찾기 요청에 필요한 출발지 좌표와 이동 방식을 검증한다."""

    origin_lat = fields.Float(data_key="originLat", required=True, validate=validate.Range(min=-90, max=90))

    origin_lng = fields.Float(data_key="originLng", required=True, validate=validate.Range(min=-180, max=180))

    mode = fields.String(load_default="transit", validate=validate.OneOf(("car", "transit", "walk")))


class DirectionsStepSchema(Schema):
    """개별 이동 단계의 응답 형식을 정의한다."""

    step_number = fields.Integer(data_key="stepNumber")
    type = fields.String()
    instruction = fields.String()

    # 소요 시간과 거리는 정수 또는 None으로 반환한다.
    duration_minutes = fields.Integer(data_key="durationMinutes", allow_none=True)
    distance_meters = fields.Integer(data_key="distanceMeters", allow_none=True)

    # 상세 정보는 딕셔너리 또는 None만 허용한다.
    detail = fields.Dict(keys=fields.String(), values=fields.Raw(), allow_none=True)


class DirectionsResponseSchema(Schema):
    """길찾기 결과의 응답 형식을 정의한다."""

    event_id = fields.Integer(data_key="eventId")
    mode = fields.String()
    departure_time = fields.String(data_key="departureTime")

    duration_minutes = fields.Integer(data_key="durationMinutes")
    distance_meters = fields.Integer(data_key="distanceMeters")

    arrival_time = fields.String(data_key="arrivalTime")
    steps = fields.List(fields.Nested(DirectionsStepSchema))
