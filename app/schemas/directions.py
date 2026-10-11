
from marshmallow import Schema, fields, validate

from app.schemas.events import QuerySchema


class DirectionsQuerySchema(QuerySchema):
    # 출발 위도
    origin_lat = fields.Float(
        data_key="originLat",
        required=True,
        validate=validate.Range(min=-90, max=90),
    )

    # 출발 경도
    origin_lng = fields.Float(
        data_key="originLng",
        required=True,
        validate=validate.Range(min=-180, max=180),
    )

    # 출발 시각
    departure_time = fields.String(
        data_key="departureTime",
        required=True,
        validate=validate.Length(min=1),
    )

    # 이동 수단: 현재 자동차만 지원
    mode = fields.String(
        load_default="car",
        validate=validate.OneOf(("car",)),
    )

class DirectionsResponseSchema(Schema):
    # 행사 ID
    event_id = fields.Integer(data_key="eventId")

    # 이동 수단
    mode = fields.String()

    # 예상 소요 시간(분)
    duration_minutes = fields.Integer(data_key="durationMinutes")

    # 이동 거리(미터)
    distance_meters = fields.Integer(data_key="distanceMeters")

    # 예상 도착 시각
    arrival_time = fields.String(data_key="arrivalTime")

