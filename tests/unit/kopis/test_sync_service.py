"""KopisSyncService 테스트 (가짜 API 주입, DB 사용)."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.events.models import Category, Event
from app.domains.kopis import sync_service as ss
from app.domains.kopis.sync_service import KopisSyncService, normalize_title, similar_titles
from app.domains.bookmarks.models import Bookmark
from app.domains.reviews.models import Review
from app.domains.users.models import User

TODAY = date(2026, 11, 8)


def item(pid="PF1", **kw):
    base = {
        "mt20id": pid, "prfnm": f"공연{pid} [대구]", "prfpdfrom": "2026.11.28", "prfpdto": "2026.11.29",
        "fcltynm": "아트벙커", "poster": f"http://www.kopis.or.kr/upload/pfmPoster/{pid}.png",
        "area": "대구광역시", "genrenm": "연극", "openrun": "N",
    }
    base.update(kw)
    return base


DETAIL = {
    "mt10id": "FC1", "pcseguidance": "전석 30,000원", "dtguidance": "토요일(14:00,17:00)",
    "entrpsnmH": "극단 초이스", "relateurl": "https://ticket.example.com/1", "updatedate": "2026-11-06 15:00:03.112494",
    "sty": None,
}
FACILITY = {"adres": "대구광역시 남구 현충로 262", "telno": "053-421-2223", "la": "35.855709600000000", "lo": "128.58320249999997"}


class FakeAPI:
    def __init__(self, pages, details=None, facilities=None, list_error=None):
        self.pages, self.details, self.facilities, self.list_error = pages, details or {}, facilities or {}, list_error
        self.calls = []

    def iter_performances(self, start, end):
        self.calls.append(("list", start, end))
        if self.list_error:
            raise self.list_error
        yield from enumerate(self.pages, 1)

    def performance(self, pid):
        self.calls.append(("detail", pid))
        value = self.details.get(pid, DETAIL)
        if isinstance(value, Exception):
            raise value
        return dict(value)

    def facility(self, fid):
        self.calls.append(("facility", fid))
        return dict(self.facilities.get(fid, FACILITY))


def run(pages, today=TODAY, **kw):
    api = FakeAPI(pages, **kw)
    return KopisSyncService(api=api).sync_performances(today=today), api


def not_refresh_day(event_id):
    """이 행의 상세 갱신 차례가 아닌 날."""
    d = TODAY
    while d.toordinal() % ss.DETAIL_REFRESH_DAYS == event_id % ss.DETAIL_REFRESH_DAYS:
        d += timedelta(days=1)
    return d


def events():
    db.session.remove()
    return {e.tour_content_id: e for e in db.session.scalars(select(Event))}


def tour_event(title, sido="27", venue="아트벙커", start=date(2026, 11, 28), end=date(2026, 11, 28), cid="T1"):
    category = db.session.scalar(select(Category).where(Category.name == "축제"))
    e = Event(tour_content_id=cid, category_id=category.id, sido_code=sido, title=title,
              start_date=start, end_date=end, venue_name=venue)
    db.session.add(e)
    db.session.commit()
    eid = e.id
    db.session.remove()
    return eid


def test_saves_new_performance_with_detail_and_facility(seeded):
    report, api = run([[item("PF1")]])
    assert report == {"saved": 1, "updated": 0, "skipped": 0, "duplicates": [], "failures": [], "complete": True}
    assert api.calls[0][1:] == (TODAY, date(2026, 12, 8))
    e = events()["KOPIS-PF1"]
    assert (e.category.name, e.sido_code, e.title) == ("공연", "27", "공연PF1 [대구]")
    assert (e.start_date, e.end_date, e.is_permanent) == (date(2026, 11, 28), date(2026, 11, 29), False)
    assert e.venue_name == "아트벙커" and e.image_url.endswith("PF1.png")
    assert (e.price, e.is_free, e.fee_text) == (30000, False, "전석 30,000원")
    assert e.play_time == "토요일(14:00,17:00)" and e.organizer == "극단 초이스"
    assert e.homepage_url == "https://ticket.example.com/1"
    assert e.tour_modified_at == datetime(2026, 11, 6, 15, 0, 3)
    assert e.address.startswith("대구광역시") and e.contact_phone == "053-421-2223"
    assert (e.latitude, e.longitude) == (Decimal("35.8557096"), Decimal("128.5832025"))
    assert e.lcls_code is None and e.description is None


def test_skips_unmapped_area_and_genre(seeded):
    report, api = run([[item("PF1", area="해외"), item("PF2", area=None), item("PF3", genrenm="미지장르"), item("PF4")]])
    assert (report["saved"], report["skipped"]) == (1, 3)
    assert [c for c in api.calls if c[0] == "detail"] == [("detail", "PF4")]


def test_existing_row_updates_from_list_only_and_keeps_detail(seeded):
    run([[item("PF1")]])
    e = events()["KOPIS-PF1"]
    e.view_count = 7
    db.session.commit()
    report, api = run([[item("PF1", prfnm="바뀐 제목", prfpdto="2026.12.05", openrun="Y")]], today=not_refresh_day(e.id))
    assert (report["saved"], report["updated"]) == (0, 1)
    assert not [c for c in api.calls if c[0] in ("detail", "facility")]
    e = events()["KOPIS-PF1"]
    assert (e.title, e.end_date, e.is_permanent, e.view_count) == ("바뀐 제목", date(2026, 12, 5), True, 7)
    assert e.fee_text == "전석 30,000원" and e.latitude is not None  # 상세 값 유지


def test_facility_fetched_once_per_run(seeded):
    _, api = run([[item("PF1"), item("PF2")]])
    assert [c for c in api.calls if c[0] == "facility"] == [("facility", "FC1")]


def test_detail_failure_recorded_others_continue(seeded):
    err = BusinessException(ErrorCode.KOPIS_REQUEST_FAILED, extra={"reason": "timeout"})
    report, _ = run([[item("PF1"), item("PF2")]], details={"PF1": err})
    assert report["saved"] == 1 and report["complete"] is False
    assert report["failures"][0]["id"] == "PF1" and report["failures"][0]["code"] == ErrorCode.KOPIS_REQUEST_FAILED.code
    assert set(events()) == {"KOPIS-PF2"}


def test_list_failure_stops(seeded):
    err = BusinessException(ErrorCode.KOPIS_REQUEST_FAILED, extra={"reason": "api_result"})
    report, _ = run([], list_error=err)
    assert report["complete"] is False and report["failures"][0]["page"] is None


@pytest.mark.parametrize("bad", [{"prfpdfrom": "2026-11-28"}, {"prfpdfrom": "2026.12.10", "prfpdto": "2026.12.01"}, {"prfnm": None}])
def test_invalid_item_rejected(seeded, bad):
    report, _ = run([[item("PF1", **bad)]])
    assert report["failures"] and events() == {}


def test_bad_coordinate_stored_as_null(seeded):
    run([[item("PF1")]], facilities={"FC1": {**FACILITY, "la": "", "lo": "999"}})
    e = events()["KOPIS-PF1"]
    assert e.latitude is None and e.longitude is None


# ---- TourAPI 우선 중복 차단 ----
@pytest.mark.parametrize("a, b, expected", [
    ("어느 북소년의 여행 [대구]", "어느 북소년의 여행", True),
    ("제3회 오브제 연극제", "오브제 연극제 2026", True),
    ("햄릿", "맥베스", False),
    ("[대학로]", "2026", False),  # 정규화 후 빈 제목은 비교하지 않는다
])
def test_similar_titles(a, b, expected):
    assert similar_titles(a, b) is expected


def test_normalize_title():
    assert normalize_title("제 3회 오브제·연극제 2026년 [대구]") == "오브제연극제"


def test_skips_when_tourapi_has_same_event(seeded):
    tid = tour_event("어느 북소년의 여행")
    report, api = run([[item("PF1", prfnm="어느 북소년의 여행 [대구]"), item("PF2")]])
    assert report["duplicates"] == [{"id": "PF1", "tour_event_id": tid, "removed": False}]
    assert ("detail", "PF1") not in api.calls  # 중복이면 상세도 부르지 않는다
    assert set(events()) == {"T1", "KOPIS-PF2"}


def test_not_duplicate_in_other_sido_or_period(seeded):
    tour_event("공연PF1", sido="11", cid="T1")
    tour_event("공연PF1", start=date(2026, 5, 1), end=date(2026, 5, 2), cid="T2")
    report, _ = run([[item("PF1")]])
    assert report["saved"] == 1 and report["duplicates"] == []


def test_lower_threshold_only_at_same_venue(seeded):
    a, b = "오브제 연극 북소년", "오브제 북소년 연극"
    assert not similar_titles(a, b) and similar_titles(a, b, 0.6)
    tour_event(b, venue="다른 극장", cid="T1")
    assert run([[item("PF1", prfnm=a)]])[0]["saved"] == 1
    tour_event(b, venue="아트벙커 소극장", cid="T2")
    assert len(run([[item("PF2", prfnm=a)]])[0]["duplicates"]) == 1


def test_existing_kopis_row_removed_when_tourapi_adds_it(seeded):
    run([[item("PF1", prfnm="북소년의 여행")]])
    tid = tour_event("북소년의 여행")
    report, _ = run([[item("PF1", prfnm="북소년의 여행")]])
    assert report["duplicates"] == [{"id": "PF1", "tour_event_id": tid, "removed": True}]
    assert set(events()) == {"T1"}


def test_existing_kopis_row_with_review_kept(seeded):
    run([[item("PF1", prfnm="북소년의 여행")]])
    kid = events()["KOPIS-PF1"].id
    user = User(kakao_id=1, email="r@example.com", nickname="리뷰어")
    db.session.add(user)
    db.session.flush()
    db.session.add(Review(user_id=user.id, event_id=kid, rating=5, content="좋아요"))
    db.session.commit()
    tour_event("북소년의 여행")
    report, _ = run([[item("PF1", prfnm="북소년의 여행")]])
    assert report["duplicates"][0]["removed"] is False
    assert set(events()) == {"T1", "KOPIS-PF1"}


def test_same_title_at_different_venue_is_not_duplicate(seeded):
    # 같은 작품이 전용관마다 따로 열린다(실제 사례: 페인터즈 광화문/서대문/경향아트힐).
    tour_event("페인터즈", venue="페인터즈 광화문 전용관")
    report, _ = run([[item("PF1", prfnm="페인터즈 [서대문전용관]", fcltynm="NH아트홀")]])
    assert report["saved"] == 1 and report["duplicates"] == []


def test_same_venue_matches_short_contained_title(seeded):
    # 실제 사례: KOPIS '진연 [서울]' @ 진연 == TourAPI '국악공연 진연' @ 진연
    tid = tour_event("국악공연 진연", venue="진연")
    report, _ = run([[item("PF1", prfnm="진연 [서울]", fcltynm="진연"), item("PF2", prfnm="덩더쿵 어린이 궁중 음악대", fcltynm="진연")]])
    assert report["duplicates"] == [{"id": "PF1", "tour_event_id": tid, "removed": False}]
    assert report["saved"] == 1  # 같은 공연장의 다른 공연은 별개


def test_venue_with_parentheses_matches(seeded):
    # 실제 사례: KOPIS 공연장 이름이 더 길고 괄호가 붙어 온다.
    tour_event("쿼드, 연극의 질문들：〈화염〉", venue="대학로극장 쿼드", sido="11")
    report, _ = run([[item("PF1", prfnm="쿼드, 연극의 질문들: 이성열의 화염", area="서울특별시",
                           fcltynm="서울문화재단 대학로극장 쿼드 (예술청) (대학로극장 쿼드 (예술청) )")]])
    assert len(report["duplicates"]) == 1


def test_missing_venue_falls_back_to_title_only(seeded):
    tour_event("북소년의 여행", venue=None)
    report, _ = run([[item("PF1", prfnm="북소년의 여행 [대구]", fcltynm="아무 극장")]])
    assert len(report["duplicates"]) == 1


def test_existing_row_refreshes_detail_on_its_day(seeded):
    run([[item("PF1")]])
    e = events()["KOPIS-PF1"]
    day = TODAY
    while day.toordinal() % ss.DETAIL_REFRESH_DAYS != e.id % ss.DETAIL_REFRESH_DAYS:
        day += timedelta(days=1)
    changed = {**DETAIL, "pcseguidance": "R석 50,000원", "dtguidance": "일요일(15:00)"}
    report, api = run([[item("PF1")]], today=day, details={"PF1": changed}, facilities={"FC1": {**FACILITY, "la": "37.5", "lo": "127.0"}})
    assert report["updated"] == 1 and ("detail", "PF1") in api.calls
    e = events()["KOPIS-PF1"]
    assert (e.fee_text, e.price, e.play_time) == ("R석 50,000원", 50000, "일요일(15:00)")
    assert (e.latitude, e.longitude) == (Decimal("37.5000000"), Decimal("127.0000000"))


@pytest.mark.parametrize("value", ["2026-11-06", "어제", None])
def test_bad_updatedate_does_not_stop_sync(seeded, value):
    report, _ = run([[item("PF1"), item("PF2")]], details={"PF1": {**DETAIL, "updatedate": value}})
    assert report["saved"] == 2 and report["complete"] is True
    assert events()["KOPIS-PF1"].tour_modified_at is None


@pytest.mark.parametrize("a, b, expected", [
    ("벡스코 (BEXCO)", "부산 벡스코 제1전시장", True),
    ("충주시문화회관", "충주탄금공원 및 충주시 문화회관", True),  # 띄어쓰기만 다름
    ("서울문화재단 대학로극장 쿼드 (예술청) (대학로극장 쿼드 (예술청) )", "대학로극장 쿼드", True),
    ("피크닉", "반포한강공원 서래섬 1교 피크닉장", False),  # 낱말 일부만 겹침(실제 오판 사례)
    ("NH아트홀", "페인터즈 광화문 전용관", False),
    ("(재)", "영화의전당", False),  # 괄호를 빼면 빈 이름
])
def test_same_venue(a, b, expected):
    assert ss._same_venue(a, b) is expected


def test_bookmarks_move_to_tourapi_event_when_kopis_row_removed(seeded):
    run([[item("PF1", prfnm="북소년의 여행")]])
    kid = events()["KOPIS-PF1"].id
    only_kopis = User(kakao_id=1, email="a@example.com", nickname="a")
    both = User(kakao_id=2, email="b@example.com", nickname="b")
    db.session.add_all([only_kopis, both])
    db.session.commit()
    uids = (only_kopis.id, both.id)
    tid = tour_event("북소년의 여행")
    db.session.add_all([Bookmark(user_id=uids[0], event_id=kid), Bookmark(user_id=uids[1], event_id=kid),
                        Bookmark(user_id=uids[1], event_id=tid)])
    db.session.commit()
    report, _ = run([[item("PF1", prfnm="북소년의 여행")]])
    assert report["duplicates"][0]["removed"] is True
    db.session.remove()
    marks = sorted((b.user_id, b.event_id) for b in db.session.scalars(select(Bookmark)))
    assert marks == sorted([(uids[0], tid), (uids[1], tid)])
