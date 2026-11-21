"""service.get_directions: 검증과 이동 방식 분기. 하위 서비스는 가짜로 대체."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.directions import service
from app.core.time import KST
from app.domains.events.models import Category, Event, Sido


@pytest.fixture()
def spy(monkeypatch):
    calls = []
    for name, attr in (("car", "get_car_directions"), ("transit", "get_transit_directions"),
                       ("walk", "get_walk_directions")):
        def fake(event, lat, lng, dep, _n=name):
            calls.append((_n, event.id, lat, lng, dep))
            return {"mode": _n}
        monkeypatch.setattr(getattr(service, f"{name}_service"), attr, fake)
    return calls


@pytest.fixture()
def make(app_ctx):
    def _make(lat="36.8", lng="127.1"):
        cat = Category(name="축제", sort_order=1)
        sido = Sido(code="44", name="충청남도", short_name="충남", sort_order=1)
        db.session.add_all([cat, sido])
        db.session.flush()
        today = datetime.now(KST).date()
        e = Event(tour_content_id="tc1", category_id=cat.id, sido_code="44", title="행사",
                  start_date=today, end_date=today + timedelta(days=3))
        db.session.add(e)
        db.session.flush()
        e.latitude = None if lat is None else Decimal(lat)
        e.longitude = None if lng is None else Decimal(lng)
        db.session.commit()
        return e.id
    return _make


def err(event_id, query):
    with pytest.raises(BusinessException) as ei:
        service.get_directions(event_id, query)
    return ei.value.error_code


@pytest.mark.parametrize("mode", ["car", "transit", "walk"])
def test_dispatch(make, spy, mode):
    eid = make()
    assert service.get_directions(eid, {"origin_lat": 37, "origin_lng": 127, "mode": mode}) == {"mode": mode}
    name, event_id, lat, lng, dep = spy[0]
    assert (name, event_id, lat, lng) == (mode, eid, 37.0, 127.0)
    assert dep.tzinfo is not None


def test_default_mode_is_transit(make, spy):
    assert service.get_directions(make(), {"origin_lat": 1, "origin_lng": 2}) == {"mode": "transit"}


def test_event_not_found(app_ctx, spy):
    assert err(999999, {"origin_lat": 1, "origin_lng": 2}) == ErrorCode.EVENT_NOT_FOUND
    assert spy == []


@pytest.mark.parametrize("lat,lng", [(None, "127"), ("36", None), (None, None)])
def test_event_without_coordinates(make, spy, lat, lng):
    assert err(make(lat, lng), {"origin_lat": 1, "origin_lng": 2}) == ErrorCode.ROUTE_NOT_FOUND


@pytest.mark.parametrize("query", [
    {}, {"origin_lat": 1}, {"origin_lat": "x", "origin_lng": 2}, {"origin_lat": None, "origin_lng": 2},
    {"origin_lat": float("nan"), "origin_lng": 2}, {"origin_lat": float("inf"), "origin_lng": 2},
    {"origin_lat": 91, "origin_lng": 2}, {"origin_lat": 1, "origin_lng": 181},
    {"origin_lat": 1, "origin_lng": 2, "mode": "bike"},
])
def test_invalid_query(make, spy, query):
    assert err(make(), query) == ErrorCode.COMMON_INVALID_INPUT
    assert spy == []


def test_destination_out_of_range_is_route_not_found(make, spy):
    assert err(make("95", "127"), {"origin_lat": 1, "origin_lng": 2}) == ErrorCode.ROUTE_NOT_FOUND
