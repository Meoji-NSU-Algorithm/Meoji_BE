"""UtcDateTime 필드 테스트."""
from datetime import datetime, timedelta, timezone

from marshmallow import Schema

from app.core.fields import UtcDateTime


class S(Schema):
    at = UtcDateTime()


def dump(v):
    return S().dump({"at": v})["at"]


def test_naive_is_treated_as_utc():
    assert dump(datetime(2026, 10, 25, 3, 0, 0)) == "2026-10-25T03:00:00+00:00"


def test_aware_is_converted_to_utc():
    kst = timezone(timedelta(hours=9))
    assert dump(datetime(2026, 10, 25, 12, 0, 0, tzinfo=kst)) == "2026-10-25T03:00:00+00:00"


def test_none_stays_none():
    assert dump(None) is None


def test_microseconds_only_when_present():
    assert dump(datetime(2026, 10, 25, 3, 0, 0, 123456)) == "2026-10-25T03:00:00.123456+00:00"
    assert "." not in dump(datetime(2026, 10, 25, 3, 0, 0))
