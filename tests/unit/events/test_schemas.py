"""events 스키마 검증과 응답 직렬화 테스트."""
import re
from datetime import date
from types import SimpleNamespace

import pytest
from marshmallow import ValidationError
from werkzeug.datastructures import MultiDict

from app.domains.events.schemas import (
    CategoryOptionSchema, EmptyQuerySchema, EventDetailResponseSchema, EventListQuerySchema,
    EventListResponseSchema, EventPathSchema, MonthlyTopQuerySchema, MonthlyTopResponseSchema,
    SidoOptionSchema,
)

SNAKE = re.compile(r"^[a-z0-9_]+$")


def load(data):
    return EventListQuerySchema().load(data)


def test_list_query_defaults():
    r = load({})
    assert r["sort"] == "latest" and r["page"] == 1 and r["size"] == 20
    assert r["q"] is None and r["is_free"] is None and r["start_date"] is None


@pytest.mark.parametrize("sort", ["latest", "popular", "dateAsc"])
def test_sort_valid(sort):
    assert load({"sort": sort})["sort"] == sort


@pytest.mark.parametrize("sort", ["date_asc", "dateasc", "", "views", "DATEASC"])
def test_sort_invalid(sort):
    with pytest.raises(ValidationError) as e:
        load({"sort": sort})
    assert "sort" in e.value.messages


@pytest.mark.parametrize("key,val", [
    ("page", "0"), ("page", "-1"), ("page", "2147483648"), ("page", "abc"),
    ("size", "0"), ("size", "101"), ("size", "-5"), ("size", "x"),
    ("category_id", "0"), ("category_id", "2147483648"),
    ("sido_code", "4"), ("sido_code", "444"), ("sido_code", "ab"),
    ("is_free", "1"), ("is_free", "True"), ("is_free", "yes"),
])
def test_invalid_scalar(key, val):
    with pytest.raises(ValidationError) as e:
        load({key: val})
    assert key in e.value.messages


def test_valid_bounds():
    r = load({"page": "2147483647", "size": "100", "category_id": "2147483647",
              "sido_code": "04", "is_free": "false"})
    assert r["page"] == 2147483647 and r["size"] == 100
    assert r["sido_code"] == "04" and r["is_free"] is False
    assert load({"size": "1"})["size"] == 1
    assert load({"is_free": "true"})["is_free"] is True


@pytest.mark.parametrize("val", ["2026/01/01", "20260101", "2026-1-1", "2026-01-01T00:00:00", " 2026-01-01"])
def test_date_format_invalid(val):
    with pytest.raises(ValidationError) as e:
        load({"start_date": val})
    assert "start_date" in e.value.messages


def test_date_nonexistent_invalid():
    with pytest.raises(ValidationError):
        load({"end_date": "2026-02-30"})


def test_date_valid_and_range():
    r = load({"start_date": "2026-01-01", "end_date": "2026-01-01"})
    assert r["start_date"] == date(2026, 1, 1)
    with pytest.raises(ValidationError) as e:
        load({"start_date": "2026-02-01", "end_date": "2026-01-01"})
    assert "end_date" in e.value.messages
    assert load({"start_date": "2026-02-01"})["end_date"] is None


@pytest.mark.parametrize("key", ["q", "title", "venue", "tag"])
def test_keyword_length(key):
    assert load({key: "a" * 100})[key] == "a" * 100
    with pytest.raises(ValidationError) as e:
        load({key: "a" * 101})
    assert key in e.value.messages


def test_unknown_param_rejected():
    with pytest.raises(ValidationError) as e:
        load({"foo": "1"})
    assert "foo" in e.value.messages


def test_camel_case_params_rejected():
    with pytest.raises(ValidationError):
        load({"categoryId": "1"})


def test_duplicate_keys_rejected():
    with pytest.raises(ValidationError):
        load(MultiDict([("page", "1"), ("page", "2")]))
    assert load(MultiDict([("page", "3")]))["page"] == 3


def test_empty_query_schema():
    assert EmptyQuerySchema().load({}) == {}
    with pytest.raises(ValidationError):
        EmptyQuerySchema().load({"a": "1"})
    with pytest.raises(ValidationError):
        EmptyQuerySchema().load(MultiDict([("a", "1"), ("a", "2")]))


@pytest.mark.parametrize("v,ok", [(1, True), (2147483647, True), (0, False), (-1, False),
                                  (2147483648, False), (10**20, False)])
def test_event_path(v, ok):
    if ok:
        assert EventPathSchema().load({"event_id": v})["event_id"] == v
    else:
        with pytest.raises(ValidationError):
            EventPathSchema().load({"event_id": v})


def test_event_path_missing_or_str():
    with pytest.raises(ValidationError):
        EventPathSchema().load({})
    with pytest.raises(ValidationError):
        EventPathSchema().load({"event_id": "abc"})


def test_monthly_defaults_and_bounds():
    r = MonthlyTopQuerySchema().load({})
    assert r["month"] is None and r["size"] == 4
    assert MonthlyTopQuerySchema().load({"month": "2026-09", "size": "20"})["month"] == date(2026, 9, 1)
    assert MonthlyTopQuerySchema().load({"size": "1"})["size"] == 1


@pytest.mark.parametrize("data", [
    {"size": "0"}, {"size": "21"}, {"size": "-1"}, {"size": "a"},
    {"month": "2026-9"}, {"month": "2026-13"}, {"month": "2026-00"}, {"month": "2026-09-01"},
    {"month": "202609"}, {"month": ""}, {"foo": "1"},
])
def test_monthly_invalid(data):
    with pytest.raises(ValidationError):
        MonthlyTopQuerySchema().load(data)


def _assert_snake(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert SNAKE.match(k), k
            _assert_snake(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_snake(v)


def _event_ns(**kw):
    d = dict(
        id=1, title="t", category_id=1, category=SimpleNamespace(name="축제"),
        sido_code="04", sido=SimpleNamespace(short_name="충남"),
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 2), venue_name=None,
        thumbnail_url=None, price=None, is_free=None, description=None, address=None,
        address_detail=None, play_time=None, fee_text=None, image_url=None, latitude=None,
        longitude=None, organizer=None, contact_phone=None, homepage_url=None,
        is_permanent=False,
    )
    d.update(kw)
    return SimpleNamespace(**d)


def test_option_schemas_snake_case():
    c = CategoryOptionSchema().dump(SimpleNamespace(id=1, name="축제", sort_order=2))
    assert c == {"id": 1, "name": "축제", "sort_order": 2}
    s = SidoOptionSchema().dump(SimpleNamespace(code="04", name="충청남도", short_name="충남", sort_order=1))
    assert s == {"code": "04", "name": "충청남도", "short_name": "충남", "sort_order": 1}


def test_list_response_dump_snake():
    out = EventListResponseSchema().dump(
        {"total_count": 1, "page": 1, "size": 20, "events": [_event_ns()]})
    _assert_snake(out)
    card = out["events"][0]
    assert card["category"] == "축제" and card["sido"] == "충남" and card["sido_code"] == "04"
    assert card["start_date"] == "2026-01-01"


def test_monthly_top_response_flat():
    out = MonthlyTopResponseSchema().dump(
        {"month": "2026-06", "events": [{"event": _event_ns(), "monthly_views": 7}]})
    _assert_snake(out)
    assert out["events"][0]["monthly_views"] == 7 and out["events"][0]["id"] == 1
    assert "event" not in out["events"][0]


def test_detail_response_flat():
    out = EventDetailResponseSchema().dump({
        "event": _event_ns(latitude=36.5, longitude=127.1),
        "reviews": [], "review_count": 0, "average_rating": 0.0,
    })
    _assert_snake(out)
    assert out["id"] == 1 and "event" not in out
    assert out["review_count"] == 0 and out["reviews"] == []
    assert out["latitude"] == 36.5
