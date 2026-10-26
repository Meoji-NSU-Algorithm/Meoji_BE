"""events 서비스(list_categories/list_sidos/list_events/monthly_top/get_event) 테스트."""
from datetime import date, datetime, timedelta

import pytest

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.events import service
from app.domains.events.models import Event, EventDailyView
from tests.unit.events.conftest import TODAY, real_today


def q(**kw):
    base = dict(q=None, title=None, venue=None, tag=None, category_id=None, sido_code=None,
                is_free=None, start_date=None, end_date=None, sort="latest", page=1, size=20)
    base.update(kw)
    return base


def ids(result):
    return [e.id for e in result["events"]]


# ---------- categories / sidos ----------
def test_categories_empty(app_ctx):
    assert service.list_categories() == []
    assert service.list_sidos() == []


def test_categories_sorted(make_category):
    b = make_category("b", 2)
    a = make_category("a", 1)
    c = make_category("c", 2)
    assert [x.id for x in service.list_categories()] == [a.id, b.id, c.id]


def test_sidos_sorted(make_sido):
    s1 = make_sido("11", sort_order=3)
    s2 = make_sido("05", sort_order=1)
    s3 = make_sido("02", sort_order=3)
    assert [x.code for x in service.list_sidos()] == [s2.code, s3.code, s1.code]


# ---------- list_events ----------
def test_list_empty(app_ctx):
    r = service.list_events(q())
    assert r == {"total_count": 0, "page": 1, "size": 20, "events": []}


def test_list_excludes_ended_includes_today(make_event):
    t = real_today()
    ended = make_event(start_date=t - timedelta(days=5), end_date=t - timedelta(days=1))
    today_end = make_event(start_date=t - timedelta(days=5), end_date=t)
    upcoming = make_event(start_date=t + timedelta(days=5), end_date=t + timedelta(days=6))
    r = service.list_events(q())
    assert set(ids(r)) == {today_end.id, upcoming.id}
    assert ended.id not in ids(r) and r["total_count"] == 2


def test_filter_category_sido(make_event, make_category, make_sido):
    c2, s2 = make_category("전시", 2), make_sido("11", "서울", "서울", 2)
    a = make_event()
    b = make_event(category=c2)
    c = make_event(sido=s2)
    assert ids(service.list_events(q(category_id=c2.id))) == [b.id]
    assert ids(service.list_events(q(sido_code="11"))) == [c.id]
    assert ids(service.list_events(q(category_id=c2.id, sido_code="11"))) == []
    assert service.list_events(q(sido_code="99"))["events"] == []
    assert a.id not in ids(service.list_events(q(category_id=c2.id)))


def test_filter_is_free(make_event):
    f = make_event(is_free=True)
    p = make_event(is_free=False)
    make_event(is_free=None)
    assert ids(service.list_events(q(is_free=True))) == [f.id]
    assert ids(service.list_events(q(is_free=False))) == [p.id]
    assert service.list_events(q())["total_count"] == 3


def test_filter_date_overlap(make_event):
    t = real_today()
    e = make_event(start_date=t + timedelta(days=10), end_date=t + timedelta(days=20))
    d = lambda n: t + timedelta(days=n)
    assert ids(service.list_events(q(start_date=d(20)))) == [e.id]  # 경계 겹침
    assert ids(service.list_events(q(start_date=d(21)))) == []
    assert ids(service.list_events(q(end_date=d(10)))) == [e.id]
    assert ids(service.list_events(q(end_date=d(9)))) == []
    assert ids(service.list_events(q(start_date=d(12), end_date=d(13)))) == [e.id]
    assert ids(service.list_events(q(start_date=d(0), end_date=d(30)))) == [e.id]


def test_keyword_q_title_venue_tag(make_event, make_tag):
    tg = make_tag("불꽃놀이")
    a = make_event(title="봄 축제")
    b = make_event(title="x", venue_name="천안 공원")
    c = make_event(title="y", tags=[tg])
    make_event(title="zzz", description="봄 불꽃놀이 천안")  # 설명은 대상이 아님
    assert ids(service.list_events(q(q="봄"))) == [a.id]
    assert ids(service.list_events(q(q="공원"))) == [b.id]
    assert ids(service.list_events(q(q="불꽃"))) == [c.id]
    assert service.list_events(q(q="없음"))["total_count"] == 0


def test_keyword_blank_ignored(make_event):
    make_event()
    assert service.list_events(q(q="   "))["total_count"] == 1


def test_keyword_case_insensitive(make_event):
    a = make_event(title="Jazz Festival")
    assert ids(service.list_events(q(q="jazz"))) == [a.id]


def test_keyword_wildcards_escaped(make_event):
    a = make_event(title="100% 할인")
    make_event(title="abc")
    b = make_event(title="a_c")
    make_event(title="a\\c")
    assert ids(service.list_events(q(q="%"))) == [a.id]
    assert ids(service.list_events(q(q="a_c"))) == [b.id]
    assert len(service.list_events(q(q="\\"))["events"]) == 1


def test_specific_fields_and_and(make_event, make_tag):
    tg = make_tag("야시장")
    a = make_event(title="봄", venue_name="천안", tags=[tg])
    b = make_event(title="봄", venue_name="서울")
    c = make_event(title="가을", venue_name="천안")
    assert set(ids(service.list_events(q(title="봄")))) == {a.id, b.id}
    assert set(ids(service.list_events(q(venue="천안")))) == {a.id, c.id}
    assert ids(service.list_events(q(tag="야시장"))) == [a.id]
    assert ids(service.list_events(q(title="봄", venue="천안"))) == [a.id]
    assert ids(service.list_events(q(title="가을", tag="야시장"))) == []


def test_tag_match_no_duplicates(make_event, make_tag):
    t1, t2 = make_tag("가나"), make_tag("가다")
    e = make_event(tags=[t1, t2])
    r = service.list_events(q(tag="가"))
    assert ids(r) == [e.id] and r["total_count"] == 1
    r = service.list_events(q(q="가"))
    assert ids(r) == [e.id] and r["total_count"] == 1


def test_tag_filter_does_not_match_title(make_event):
    make_event(title="불꽃")
    assert service.list_events(q(tag="불꽃"))["total_count"] == 0


def test_sort_latest(make_event):
    now = datetime(2026, 1, 1, 12)
    a = make_event(created_at=now)
    b = make_event(created_at=now + timedelta(hours=1))
    c = make_event(created_at=now)  # a와 동률 -> id 내림차순
    assert ids(service.list_events(q(sort="latest"))) == [b.id, c.id, a.id]


def test_sort_popular(make_event):
    a = make_event(view_count=5)
    b = make_event(view_count=50)
    c = make_event(view_count=5)
    assert ids(service.list_events(q(sort="popular"))) == [b.id, c.id, a.id]


def test_sort_date_asc(make_event):
    t = real_today()
    a = make_event(start_date=t + timedelta(days=5), end_date=t + timedelta(days=9))
    b = make_event(start_date=t + timedelta(days=1), end_date=t + timedelta(days=9))
    c = make_event(start_date=t + timedelta(days=1), end_date=t + timedelta(days=9))
    assert ids(service.list_events(q(sort="dateAsc"))) == [b.id, c.id, a.id]


def test_pagination(make_event):
    now = datetime(2026, 1, 1)
    evs = [make_event(created_at=now + timedelta(minutes=i)) for i in range(5)]
    order = [e.id for e in reversed(evs)]
    r1 = service.list_events(q(size=2, page=1))
    r2 = service.list_events(q(size=2, page=2))
    r3 = service.list_events(q(size=2, page=3))
    assert ids(r1) == order[:2] and ids(r2) == order[2:4] and ids(r3) == order[4:]
    assert r1["total_count"] == r2["total_count"] == r3["total_count"] == 5
    assert (r2["page"], r2["size"]) == (2, 2)


def test_page_past_end(make_event):
    make_event()
    r = service.list_events(q(page=999, size=20))
    assert r["events"] == [] and r["total_count"] == 1 and r["page"] == 999
    r = service.list_events(q(page=2147483647, size=100))
    assert r["events"] == [] and r["total_count"] == 1


def test_list_events_loads_relations(make_event):
    make_event()
    e = service.list_events(q())["events"][0]
    db.session.expunge_all()
    assert e.category.name == "축제" and e.sido.short_name == "충남"


# ---------- monthly_top ----------
def mq(month=None, size=4):
    return {"month": month, "size": size}


def test_monthly_top_empty(app_ctx):
    r = service.monthly_top(mq(), today=TODAY)
    assert r == {"month": "2026-06", "events": []}


def test_monthly_top_ranking_and_month_boundary(make_event, make_daily_view):
    end = date(2026, 12, 31)
    a = make_event(end_date=end)
    b = make_event(end_date=end)
    c = make_event(end_date=end)
    make_daily_view(a, date(2026, 6, 1), 3)
    make_daily_view(a, date(2026, 6, 30), 4)       # a = 7 (경계 포함)
    make_daily_view(a, date(2026, 5, 31), 100)     # 다른 달
    make_daily_view(a, date(2026, 7, 1), 100)      # 다른 달
    make_daily_view(b, date(2026, 6, 10), 9)
    make_daily_view(c, date(2026, 6, 10), 9)       # b와 동률 -> id 내림차순
    r = service.monthly_top(mq(size=3), today=TODAY)
    assert [(x["event"].id, x["monthly_views"]) for x in r["events"]] == [
        (c.id, 9), (b.id, 9), (a.id, 7)]


def test_monthly_top_explicit_month(make_event, make_daily_view):
    a = make_event(end_date=date(2026, 12, 31))
    make_daily_view(a, date(2026, 2, 28), 2)
    r = service.monthly_top(mq(month=date(2026, 2, 1), size=1), today=TODAY)
    assert r["month"] == "2026-02"
    assert [(x["event"].id, x["monthly_views"]) for x in r["events"]] == [(a.id, 2)]


def test_monthly_top_leap_february(make_event, make_daily_view):
    a = make_event(end_date=date(2028, 12, 31))
    make_daily_view(a, date(2028, 2, 29), 2)
    r = service.monthly_top(mq(month=date(2028, 2, 1), size=1), today=date(2028, 3, 1))
    assert r["events"][0]["monthly_views"] == 2


def test_monthly_top_limit(make_event, make_daily_view):
    for i in range(5):
        make_daily_view(make_event(end_date=date(2026, 12, 31)), date(2026, 6, 2), i + 1)
    r = service.monthly_top(mq(size=2), today=TODAY)
    assert [x["monthly_views"] for x in r["events"]] == [5, 4]


def test_monthly_top_excludes_ended(make_event, make_daily_view):
    ended = make_event(start_date=date(2026, 5, 1), end_date=date(2026, 6, 14))
    live = make_event(start_date=date(2026, 5, 1), end_date=date(2026, 6, 15))
    make_daily_view(ended, date(2026, 6, 2), 99)
    make_daily_view(live, date(2026, 6, 2), 1)
    r = service.monthly_top(mq(size=1), today=TODAY)
    assert [x["event"].id for x in r["events"]] == [live.id]


def test_monthly_top_fills_with_zero_views(make_event, make_daily_view):
    ranked = make_event(end_date=date(2026, 12, 31))
    soon = make_event(start_date=date(2026, 6, 1), end_date=date(2026, 6, 20))
    later = make_event(start_date=date(2026, 6, 1), end_date=date(2026, 8, 20))
    make_event(start_date=date(2026, 1, 1), end_date=date(2026, 3, 1))  # ended
    make_daily_view(ranked, date(2026, 6, 2), 3)
    r = service.monthly_top(mq(size=3), today=TODAY)
    got = [(x["event"].id, x["monthly_views"]) for x in r["events"]]
    assert got == [(ranked.id, 3), (soon.id, 0), (later.id, 0)]


def test_monthly_top_zero_count_rows_not_ranked(make_event, make_daily_view):
    a = make_event(end_date=date(2026, 12, 31))
    make_daily_view(a, date(2026, 6, 2), 0)
    r = service.monthly_top(mq(size=1), today=TODAY)
    # 순위에는 없고 채우기 대상으로만 나온다
    assert r["events"][0]["monthly_views"] == 0


# ---------- get_event ----------
def test_get_event_not_found(app_ctx):
    with pytest.raises(BusinessException) as e:
        service.get_event(999, today=TODAY)
    assert e.value.error_code == ErrorCode.EVENT_NOT_FOUND
    assert e.value.status_code == 404


def test_get_event_not_found_head(app_ctx):
    with pytest.raises(BusinessException):
        service.get_event(999, today=TODAY, request_method="HEAD")


def test_get_event_shape_and_relations(make_event):
    ev = make_event(title="상세", price=1000, is_free=False)
    got = service.get_event(ev.id, today=TODAY)
    assert got.id == ev.id and got.title == "상세"
    # 세션이 닫힌 뒤에도 관계 접근 가능해야 한다
    assert got.category.name == "축제" and got.sido.short_name == "충남"


def test_view_count_same_day_twice(make_event):
    ev = make_event()
    service.get_event(ev.id, today=TODAY)
    service.get_event(ev.id, today=TODAY)
    db.session.rollback()  # 별도 세션 커밋을 보려면 스냅샷을 새로 시작
    rows = db.session.query(EventDailyView).filter_by(event_id=ev.id).all()
    assert len(rows) == 1 and rows[0].view_count == 2 and rows[0].view_date == TODAY
    db.session.rollback()
    db.session.expire_all()
    assert db.session.get(Event, ev.id).view_count == 2


def test_view_count_different_days(make_event):
    ev = make_event()
    service.get_event(ev.id, today=TODAY)
    service.get_event(ev.id, today=TODAY + timedelta(days=1))
    db.session.rollback()
    rows = db.session.query(EventDailyView).filter_by(event_id=ev.id).order_by(EventDailyView.view_date).all()
    assert [(r.view_date, r.view_count) for r in rows] == [(TODAY, 1), (TODAY + timedelta(days=1), 1)]
    db.session.rollback()
    db.session.expire_all()
    assert db.session.get(Event, ev.id).view_count == 2


def test_view_counts_isolated_per_event(make_event):
    a, b = make_event(), make_event()
    service.get_event(a.id, today=TODAY)
    assert db.session.query(EventDailyView).filter_by(event_id=b.id).count() == 0


def test_head_does_not_count(make_event):
    ev = make_event()
    got = service.get_event(ev.id, today=TODAY, request_method="HEAD")
    assert got.id == ev.id
    assert db.session.query(EventDailyView).count() == 0
    db.session.rollback()
    db.session.expire_all()
    assert db.session.get(Event, ev.id).view_count == 0


def test_ended_event_viewable(make_event):
    t = real_today()
    ev = make_event(start_date=t - timedelta(days=30), end_date=t - timedelta(days=20))
    assert service.get_event(ev.id).id == ev.id


def test_view_does_not_touch_updated_at(make_event):
    ev = make_event()
    before = db.session.get(Event, ev.id).updated_at
    service.get_event(ev.id, today=TODAY)
    db.session.rollback()
    db.session.expire_all()
    assert db.session.get(Event, ev.id).updated_at == before


def test_view_default_today_is_kst(make_event):
    ev = make_event()
    service.get_event(ev.id)
    db.session.rollback()
    row = db.session.query(EventDailyView).filter_by(event_id=ev.id).one()
    assert row.view_date == real_today()


def test_view_count_feeds_monthly_top(make_event):
    ev = make_event(end_date=date(2026, 12, 31))
    service.get_event(ev.id, today=date(2026, 6, 3))
    service.get_event(ev.id, today=date(2026, 6, 4))
    db.session.rollback()
    r = service.monthly_top(mq(size=1), today=TODAY)
    assert r["events"][0]["monthly_views"] == 2
