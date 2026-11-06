"""길찾기 요청/응답 스키마 테스트."""
import pytest
from marshmallow import ValidationError
from werkzeug.datastructures import MultiDict

from app.domains.directions.schemas import (
    DirectionsQuerySchema,
    DirectionsResponseSchema,
    DirectionsStepSchema,
)


def load(**query):
    return DirectionsQuerySchema().load(query)


def test_query_converts_strings_and_defaults_to_transit():
    data = load(originLat="36.8", originLng="127.1")

    assert data == {"origin_lat": 36.8, "origin_lng": 127.1, "mode": "transit"}


@pytest.mark.parametrize("mode", ["car", "transit", "walk"])
def test_query_accepts_each_mode(mode):
    assert load(originLat="36.8", originLng="127.1", mode=mode)["mode"] == mode


@pytest.mark.parametrize(
    "query, bad_field",
    [
        ({"originLng": "127.1"}, "originLat"),
        ({"originLat": "36.8"}, "originLng"),
        ({"originLat": "91", "originLng": "127.1"}, "originLat"),
        ({"originLat": "-91", "originLng": "127.1"}, "originLat"),
        ({"originLat": "36.8", "originLng": "181"}, "originLng"),
        ({"originLat": "36.8", "originLng": "-181"}, "originLng"),
        ({"originLat": "nan", "originLng": "127.1"}, "originLat"),
        ({"originLat": "36.8", "originLng": "inf"}, "originLng"),
        ({"originLat": "abc", "originLng": "127.1"}, "originLat"),
        ({"originLat": "36.8", "originLng": "127.1", "mode": "bike"}, "mode"),
        ({"originLat": "36.8", "originLng": "127.1", "toLat": "37"}, "toLat"),
    ],
)
def test_query_rejects_invalid_values(query, bad_field):
    with pytest.raises(ValidationError) as exc:
        DirectionsQuerySchema().load(query)

    assert bad_field in exc.value.messages


def test_query_rejects_repeated_keys():
    args = MultiDict([("originLat", "36.8"), ("originLat", "37.0"), ("originLng", "127.1")])

    with pytest.raises(ValidationError) as exc:
        DirectionsQuerySchema().load(args)

    assert "originLat" in exc.value.messages


def test_query_boundary_values_are_allowed():
    data = load(originLat="-90", originLng="180")

    assert (data["origin_lat"], data["origin_lng"]) == (-90.0, 180.0)


def test_response_dumps_camel_case_keys():
    result = DirectionsResponseSchema().dump({
        "event_id": 1,
        "mode": "car",
        "departure_time": "2026-11-06T12:00:00+09:00",
        "duration_minutes": 25,
        "distance_meters": 12345,
        "arrival_time": "2026-11-06T12:25:00+09:00",
        "steps": [{
            "step_number": 1, "type": "DRIVE", "instruction": "출발",
            "duration_minutes": None, "distance_meters": 250, "detail": None,
        }],
    })

    assert set(result) == {
        "eventId", "mode", "departureTime", "durationMinutes",
        "distanceMeters", "arrivalTime", "steps",
    }
    assert set(result["steps"][0]) == {
        "stepNumber", "type", "instruction", "durationMinutes", "distanceMeters", "detail",
    }
    assert result["steps"][0]["durationMinutes"] is None
    assert result["steps"][0]["detail"] is None


@pytest.mark.xfail(
    strict=True, raises=ValueError,
    reason="이슈: 외부 응답 값이 숫자가 아니면 dump에서 ValueError가 나 500이 된다(transit step 미검증).",
)
def test_step_dump_with_non_numeric_duration_does_not_raise():
    DirectionsStepSchema().dump({"duration_minutes": "abc"})
