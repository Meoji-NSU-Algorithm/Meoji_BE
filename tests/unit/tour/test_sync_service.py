"""TourSyncService.sync_festivals / _save 테스트 (FakeAPI 주입, DB 사용)."""
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.events.models import Event, Sido
from app.domains.tour.sync_service import TourSyncService

from .conftest import FakeAPI, list_item


def run(items, common=None, intro=None, **kw):
    api = FakeAPI(items, common, intro, **kw)
    return TourSyncService(api=api).sync_festivals(today=date(2026, 10, 25)), api


def events():
    db.session.remove()
    return {e.tour_content_id: e for e in db.session.scalars(select(Event))}


def codes(report):
    return [f["code"] for f in report["failures"]]


def test_inserts_with_all_fields(seeded):
    items = [
        list_item("1", lclsSystm3="EV010100", lDongRegnCd="44"),
        list_item("2", lclsSystm3="EV020100", lDongRegnCd="11", title="공연", eventenddate="20261001"),
        list_item("3", lclsSystm3="EV010500", lDongRegnCd="36110", eventstartdate="20260101", eventenddate="20261231"),
    ]
    common = {"1": {"overview": "불꽃놀이와 가족 공연, 꽃 구경", "homepage": '<a href="https://ex.com">x</a>',
                    "addr1": " 천안시 ", "firstimage": "http://i/1.jpg"}}
    intro = {"1": {"usetimefestival": "성인 5,000원", "eventplace": "공원", "sponsor1": "시청", "playtime": "10시"}}
    report, _ = run(items, common, intro)
    assert report["saved"] == 3 and report["failures"] == [] and report["complete"] is True
    ev = events()
    e1 = ev["1"]
    assert (e1.category.name, e1.sido_code, e1.title) == ("축제", "44", "축제1")
    assert (e1.start_date, e1.end_date) == (date(2026, 10, 1), date(2026, 10, 5))
    assert e1.latitude == Decimal("36.8000000") and e1.longitude == Decimal("127.1500000")
    assert (e1.price, e1.is_free) == (5000, False) and e1.fee_text == "성인 5,000원"
    assert e1.homepage_url == "https://ex.com" and e1.address == "천안시"
    assert e1.venue_name == "공원" and e1.organizer == "시청" and e1.play_time == "10시"
    assert sorted(t.name for t in e1.tags) == ["가족", "공연", "꽃", "불꽃놀이"]
    assert e1.tour_modified_at == datetime(2026, 10, 1, 12, 0, 0)
    assert e1.is_permanent is False and e1.lcls_code == "EV010100"
    assert ev["2"].category.name == "공연"
    assert ev["3"].category.name == "계절행사" and ev["3"].sido_code == "36" and ev["3"].is_permanent is True


def test_default_period_passed_to_api(seeded):
    _, api = run([])
    assert api.calls == [("list", "20261018", None)]


def test_explicit_period_not_overridden(seeded):
    api = FakeAPI([])
    TourSyncService(api=api).sync_festivals("20260101", "20261231", today=date(2026, 10, 25))
    assert api.calls == [("list", "20260101", "20261231")]


def test_free_fee(seeded):
    run([list_item("1")], intro={"1": {"usetimefestival": "무료"}})
    e = events()["1"]
    assert (e.price, e.is_free) == (0, True)


def test_upsert_no_duplicates_and_fields_update(seeded):
    run([list_item("1")], {"1": {"overview": "음악 축제"}}, {"1": {"usetimefestival": "무료"}})
    first = events()["1"]
    first_id = first.id
    # 조회수는 재수집으로 덮어쓰면 안 된다.
    first.view_count = 77
    db.session.commit()
    report, _ = run(
        [list_item("1", title="새 제목", eventenddate="20261010", modifiedtime="20261020000000")],
        {"1": {"overview": "가족 야간 체험"}},
        {"1": {"usetimefestival": "3,000원"}},
    )
    assert report["complete"] and report["saved"] == 1
    ev = events()
    assert len(ev) == 1
    e = ev["1"]
    assert e.id == first_id and e.title == "새 제목" and e.end_date == date(2026, 10, 10)
    assert (e.price, e.is_free) == (3000, False)
    assert sorted(t.name for t in e.tags) == ["가족", "야간", "체험"]
    assert e.view_count == 77
    assert e.tour_modified_at == datetime(2026, 10, 20)


def test_rerun_without_overview_keeps_tags_and_description(seeded):
    run([list_item("1")], {"1": {"overview": "음악"}})
    run([list_item("1")], {"1": {}})
    e = events()["1"]
    assert e.description == "음악" and [t.name for t in e.tags] == ["음악"]


def test_empty_string_field_nulls_existing(seeded):
    run([list_item("1")], {"1": {"addr1": "서울"}})
    run([list_item("1")], {"1": {"addr1": "  "}})
    assert events()["1"].address is None


def test_empty_overview_clears_tags(seeded):
    run([list_item("1")], {"1": {"overview": "음악"}})
    run([list_item("1")], {"1": {"overview": ""}})
    assert events()["1"].tags == []


def test_no_modified_time_skipping_details_refetched(seeded):
    # modifiedtime이 같아도 건너뛰지 않고 매번 상세를 다시 조회·저장한다(현재 구현 문서화).
    api = FakeAPI([list_item("1")])
    calls = []
    orig = api.festival_common
    api.festival_common = lambda c: (calls.append(c), orig(c))[1]
    svc = TourSyncService(api=api)
    svc.sync_festivals(today=date(2026, 10, 25))
    svc.sync_festivals(today=date(2026, 10, 25))
    assert calls == ["1", "1"]


def test_ended_festival_is_still_saved(seeded):
    report, _ = run([list_item("1", eventstartdate="20200101", eventenddate="20200105")])
    assert report["saved"] == 1 and events()["1"].end_date == date(2020, 1, 5)


def test_exactly_90_days_not_permanent_91_is_(seeded):
    run([list_item("1", eventstartdate="20261001", eventenddate="20261230"),   # 90일 차
         list_item("2", eventstartdate="20261001", eventenddate="20261231")])  # 91일 차
    ev = events()
    assert ev["1"].is_permanent is False and ev["2"].is_permanent is True


def test_detail_overrides_list_and_empty_detail_date_does_not(seeded):
    run([list_item("1")], {"1": {"title": "상세제목", "eventstartdate": ""}}, {"1": {"eventenddate": "20261008"}})
    e = events()["1"]
    assert e.title == "상세제목" and e.start_date == date(2026, 10, 1) and e.end_date == date(2026, 10, 8)


# ---- 실패 처리 ----
def test_unknown_sido_code_29_missing_from_seed(seeded):
    """FINDING: 마이그레이션이 29(광주)/46(전남)을 시드하지 않아 해당 지역 축제는 SEED_MISSING으로 실패한다."""
    report, _ = run([list_item("1", lDongRegnCd="29"), list_item("2", lDongRegnCd="46"), list_item("3")])
    assert report["saved"] == 1 and report["complete"] is False
    assert codes(report) == ["TOUR_SYNC_SEED_MISSING"] * 2
    assert report["failures"][0]["extra"]["sido_code"] == "29"
    assert set(events()) == {"3"}


def test_migration_seed_sido_codes_documented():
    import importlib.util, pathlib
    # 실행 위치와 무관하게 이 파일 기준으로 저장소 루트의 migrations 를 찾는다.
    versions = pathlib.Path(__file__).resolve().parents[3] / "migrations" / "versions"
    path = next(versions.glob("62d4e8a91b03*.py"))
    spec = importlib.util.spec_from_file_location("mig", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    codes_ = {c for c, *_ in mod.SIDOS}
    assert len(codes_) == 16
    assert "29" not in codes_ and "46" not in codes_ and "12" in codes_


def test_unknown_category_code_fails_item(seeded):
    report, _ = run([list_item("1", lclsSystm3="EV990000"), list_item("2")])
    assert report["saved"] == 1 and not report["complete"]
    assert report["failures"][0]["code"] == "TOUR_SYNC_INVALID_DATA"
    assert report["failures"][0]["extra"]["reason"] == "unknown_category"


def test_missing_category_seed_row(seeded):
    from app.domains.events.models import Category
    db.session.query(Category).filter_by(name="축제").delete()
    db.session.commit()
    report, _ = run([list_item("1")])
    assert codes(report) == ["TOUR_SYNC_SEED_MISSING"] and report["saved"] == 0


def test_missing_tag_seed(seeded):
    from app.domains.events.models import Tag
    db.session.query(Tag).filter_by(name="꽃").delete()
    db.session.commit()
    report, _ = run([list_item("1")], {"1": {"overview": "꽃 축제"}})
    assert codes(report) == ["TOUR_SYNC_SEED_MISSING"] and events() == {}


@pytest.mark.parametrize("sido", ["", "x1", "1", None])
def test_invalid_sido_format(seeded, sido):
    item = list_item("1")
    if sido is None:
        del item["lDongRegnCd"]
    else:
        item["lDongRegnCd"] = sido
    report, _ = run([item])
    assert codes(report) == ["TOUR_SYNC_INVALID_DATA"]
    assert report["failures"][0]["extra"]["reason"] == "invalid_sido"


def test_detail_failure_skips_only_that_item(seeded):
    boom = BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "timeout"})
    report, _ = run([list_item("1"), list_item("2"), list_item("3")], common={"2": boom})
    assert report["saved"] == 2 and report["complete"] is False
    assert set(events()) == {"1", "3"}
    f = report["failures"][0]
    assert f["content_id"] == "2" and f["code"] == "TOUR_API_REQUEST_FAILED" and f["page"] == 1
    assert f["extra"] == {"reason": "timeout"}


def test_intro_failure_skips_item(seeded):
    boom = BusinessException(ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"reason": "detail_count"})
    report, _ = run([list_item("1"), list_item("2")], intro={"1": boom})
    assert report["saved"] == 1 and set(events()) == {"2"}


def test_failed_update_rolls_back_existing_row(seeded):
    run([list_item("1")], {"1": {"overview": "음악"}})
    # 새 응답은 잘못된 날짜 -> 전체 롤백, 기존 값 유지(태그 포함).
    report, _ = run([list_item("1", title="바뀜")], {"1": {"overview": "가족"}}, {"1": {"eventenddate": "20260230"}})
    assert not report["complete"]
    e = events()["1"]
    assert e.title == "축제1" and [t.name for t in e.tags] == ["음악"]


@pytest.mark.parametrize("override,reason", [
    ({"eventstartdate": "20261010", "eventenddate": "20261001"}, "start_after_end"),
    ({"eventstartdate": "bad"}, "invalid_date"),
    ({"mapy": "127.5"}, "coordinate_out_of_range"),
    ({"mapx": "abc"}, "invalid_coordinate"),
    ({"modifiedtime": "2026"}, "invalid_datetime"),
    ({"contenttypeid": "12"}, "not_festival"),
    ({"contentid": ""}, "invalid_id"),
    ({"contentid": "x" * 21}, "invalid_id"),
    ({"title": "t" * 201}, "field_too_long"),
    ({"homepage": ["a"]}, "invalid_field_type"),
])
def test_item_validation_failures(seeded, override, reason):
    report, _ = run([list_item("1", **override)])
    assert report["saved"] == 0 and not report["complete"]
    assert report["failures"][0]["extra"]["reason"] == reason
    assert events() == {}


def test_missing_title_and_dates_required(seeded):
    item = list_item("1")
    del item["title"]
    r, _ = run([item])
    assert codes(r) == ["TOUR_SYNC_REQUIRED_FIELD"]
    item = list_item("1")
    del item["eventstartdate"]
    r, _ = run([item])
    assert codes(r) == ["TOUR_SYNC_REQUIRED_FIELD"]


def test_detail_id_mismatch_fails(seeded):
    report, _ = run([list_item("1")], common={"1": {"contentid": "999"}})
    assert codes(report) == ["TOUR_SYNC_ID_MISMATCH"]


def test_non_dict_item_does_not_crash(seeded):
    report, _ = run(["oops", None, list_item("1")])
    assert report["saved"] == 1 and len(report["failures"]) == 2
    assert report["failures"][0]["content_id"] is None


def test_integer_contentid_and_bool_rejected(seeded):
    report, _ = run([list_item(5), list_item(True)])
    assert report["saved"] == 1 and events().keys() == {"5"}


def test_list_failure_reported_incomplete(seeded):
    err = BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE, extra={"reason": "repeated_page"})
    report, _ = run([], list_error=err)
    assert report == {"saved": 0, "complete": False, "failures": [{
        "page": None, "content_id": None, "code": "TOUR_API_INVALID_RESPONSE",
        "reason": err.message, "extra": {"reason": "repeated_page"}}]}


def test_no_items_is_complete(seeded):
    report, _ = run([])
    assert report == {"saved": 0, "failures": [], "complete": True}


def test_does_not_delete_events_missing_from_list(seeded):
    run([list_item("1"), list_item("2")])
    run([list_item("1")])
    assert set(events()) == {"1", "2"}


def test_duplicate_item_in_same_run_upserts_once(seeded):
    report, _ = run([list_item("1"), list_item("1", title="두번째")])
    assert report["saved"] == 2 and len(events()) == 1 and events()["1"].title == "두번째"


def test_missing_key_raises_lazily(app_ctx):
    app_ctx.config["TOURAPI_KEY"] = None
    try:
        svc = TourSyncService()
        with pytest.raises(BusinessException) as e:
            svc.api
        assert e.value.error_code == ErrorCode.TOUR_API_KEY_MISSING
    finally:
        app_ctx.config["TOURAPI_KEY"] = "test-tourapi-key"


def test_missing_key_in_sync_festivals_reported_not_raised(app_ctx):
    app_ctx.config["TOURAPI_KEY"] = None
    try:
        report = TourSyncService().sync_festivals()
    except BusinessException as e:
        pytest.fail(f"sync_festivals가 키 누락을 report로 담지 않고 예외를 던짐: {e.error_code}")
    finally:
        app_ctx.config["TOURAPI_KEY"] = "test-tourapi-key"
    assert report["complete"] is False
    assert report["failures"][0]["code"] == "TOUR_API_KEY_MISSING"


def test_sido_5digit_prefix_only(seeded):
    run([list_item("1", lDongRegnCd="36110")])
    assert events()["1"].sido_code == "36"
    assert db.session.get(Sido, "36") is not None


def test_price_overflow_item_fails(seeded):
    report, _ = run([list_item("1")], intro={"1": {"usetimefestival": "99,999,999,999원"}})
    assert report["failures"][0]["extra"]["reason"] == "price_out_of_range"


def test_overlong_coordinate_precision_rounds_not_fails(seeded):
    report, _ = run([list_item("1", mapx="127.123456789", mapy="36.123456789")])
    assert report["saved"] == 1
    assert events()["1"].longitude == Decimal("127.1234568")


def _fail_save_for(monkeypatch, bad_id, error):
    """bad_id 건의 _save만 주어진 예외로 실패시킨다."""
    original = TourSyncService._save

    def fake(self, item, common, intro):
        if item["contentid"] == bad_id:
            raise error
        return original(self, item, common, intro)

    monkeypatch.setattr(TourSyncService, "_save", fake)


def test_transient_db_error_skips_only_that_item(seeded, monkeypatch):
    from sqlalchemy.exc import OperationalError

    _fail_save_for(monkeypatch, "2", OperationalError("SELECT secret", {}, Exception("deadlock 1213")))
    report, _ = run([list_item("1"), list_item("2"), list_item("3")])
    assert report["saved"] == 2 and report["complete"] is False
    assert len(report["failures"]) == 1
    failure = report["failures"][0]
    assert failure["content_id"] == "2" and failure["page"] == 1
    assert failure["code"] == ErrorCode.TOUR_SYNC_DB_CONFLICT.code
    assert failure["extra"] == {"reason": "database_error", "error_type": "OperationalError"}
    # 원문 SQL·DB 메시지는 보고서에 남지 않는다.
    assert "secret" not in str(failure) and "deadlock" not in str(failure)
    assert set(events()) == {"1", "3"}


def test_non_db_unexpected_error_still_propagates(seeded, monkeypatch):
    _fail_save_for(monkeypatch, "2", RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        run([list_item("1"), list_item("2"), list_item("3")])
