import pytest
from marshmallow import ValidationError
from werkzeug.datastructures import MultiDict

from app.domains.directions.core.utils import valid_number_or_none
from app.domains.directions.schemas import DirectionsQuerySchema, DirectionsResponseSchema


def load(data):
    return DirectionsQuerySchema().load(MultiDict(data))


def test_query_defaults_mode_to_transit():
    assert load({"originLat": "37.5", "originLng": "127"}) == {
        "origin_lat": 37.5, "origin_lng": 127.0, "mode": "transit"}


@pytest.mark.parametrize("mode", ["car", "transit", "walk"])
def test_query_valid_modes(mode):
    assert load({"originLat": "1", "originLng": "2", "mode": mode})["mode"] == mode


@pytest.mark.parametrize("data", [
    {"originLng": "127"},
    {"originLat": "37"},
    {"originLat": "91", "originLng": "127"},
    {"originLat": "-91", "originLng": "127"},
    {"originLat": "37", "originLng": "181"},
    {"originLat": "37", "originLng": "-181"},
    {"originLat": "abc", "originLng": "127"},
    {"originLat": "37", "originLng": "127", "mode": "bike"},
    {"originLat": "37", "originLng": "127", "mode": "CAR"},
    {"originLat": "37", "originLng": "127", "extra": "1"},
])
def test_query_rejects_invalid(data):
    with pytest.raises(ValidationError):
        load(data)


def test_query_rejects_duplicate_keys():
    with pytest.raises(ValidationError):
        DirectionsQuerySchema().load(MultiDict([("originLat", "1"), ("originLat", "2"), ("originLng", "3")]))


@pytest.mark.parametrize("lat", [90, -90])
def test_query_boundaries_ok(lat):
    assert load({"originLat": str(lat), "originLng": "180"})["origin_lat"] == lat


@pytest.mark.parametrize("v", ["nan", "inf"])
def test_query_nan_inf_behavior(v):
    """NaN/Infinity 는 Range 검증에서 걸러지거나 로드 시 거부되어야 한다."""
    with pytest.raises(ValidationError):
        load({"originLat": v, "originLng": "127"})


def test_response_dump_camel_case_keys():
    data = {
        "event_id": 1, "mode": "car", "departure_time": "d", "duration_minutes": 3,
        "distance_meters": 10, "arrival_time": "a", "path": [[1, 2]],
        "steps": [{"step_number": 1, "type": "DRIVE", "instruction": "go",
                   "duration_minutes": None, "distance_meters": 5, "detail": None}],
    }
    out = DirectionsResponseSchema().dump(data)
    assert out["eventId"] == 1 and out["departureTime"] == "d" and out["arrivalTime"] == "a"
    assert out["durationMinutes"] == 3 and out["distanceMeters"] == 10
    assert out["path"] == [[1, 2]]
    step = out["steps"][0]
    assert step["stepNumber"] == 1 and step["durationMinutes"] is None and step["detail"] is None
    assert "event_id" not in out


@pytest.mark.parametrize("value,expected", [
    (0, 0), (5, 5), (1.5, 1.5), (-1, None), (True, None), ("1", None),
    (None, None), (float("nan"), None), (float("inf"), None),
])
def test_valid_number_or_none(value, expected):
    assert valid_number_or_none(value) == expected
