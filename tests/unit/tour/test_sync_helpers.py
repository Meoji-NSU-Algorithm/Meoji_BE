"""sync_service 모듈 수준 순수 함수 테스트."""
from decimal import Decimal

import pytest

from app.core.errors import BusinessException, ErrorCode
from app.domains.tour.sync_service import (
    _category, _coordinate, _date, _fee, _homepage_url, _modified, _value,
)


def invalid(fn, *args):
    with pytest.raises(BusinessException) as e:
        fn(*args)
    assert e.value.error_code == ErrorCode.TOUR_SYNC_INVALID_DATA
    return e.value.extra


# ---- _value ----
def test_value():
    assert _value({"a": "  x "}, "a") == "x"
    assert _value({"a": 5}, "a") == 5
    assert _value({}, "a") is None
    assert _value({"a": "   "}, "a") == ""
    assert _value({"a": None}, "a") is None


# ---- _date ----
def test_date_ok():
    assert str(_date("20261001", "f")) == "2026-10-01"
    assert str(_date(20240229, "f")) == "2024-02-29"


@pytest.mark.parametrize("bad", ["", None, "2026-10-01", "20261301", "20250229", "00000000", "2026100", " 20261001", "20261001\n"])
def test_date_bad(bad):
    assert invalid(_date, bad, "eventstartdate") == {"field": "eventstartdate", "reason": "invalid_date"}


# ---- _modified ----
def test_modified_ok():
    assert _modified("20261001235959").isoformat() == "2026-10-01T23:59:59"


@pytest.mark.parametrize("bad", ["", None, "20261001", "20261001246000", "20261001236000", "20261301000000", "2026100112000"])
def test_modified_bad(bad):
    assert invalid(_modified, bad)["field"] == "modifiedtime"


# ---- _coordinate ----
def test_coordinate_empty():
    assert _coordinate(None, "mapy", 90) is None
    assert _coordinate("", "mapy", 90) is None


def test_coordinate_ok_and_bounds():
    assert _coordinate("36.8065", "mapy", 90) == Decimal("36.8065")
    assert _coordinate("90", "mapy", 90) == 90
    assert _coordinate("-90", "mapy", 90) == -90
    assert _coordinate("180", "mapx", 180) == 180
    assert _coordinate(127.15, "mapx", 180) == Decimal("127.15")
    assert _coordinate(" 36.5 ", "mapy", 90) == Decimal("36.5")


def test_coordinate_out_of_range():
    assert invalid(_coordinate, "90.0000001", "mapy", 90)["reason"] == "coordinate_out_of_range"
    assert invalid(_coordinate, "-180.1", "mapx", 180)["reason"] == "coordinate_out_of_range"


def test_coordinate_swapped_lat_lng_detected():
    # 위도 자리에 경도(127.x)가 들어오면 거부한다.
    assert invalid(_coordinate, "127.15", "mapy", 90)["reason"] == "coordinate_out_of_range"


@pytest.mark.parametrize("bad", ["abc", "1,5", "36.8.1", "--1"])
def test_coordinate_malformed(bad):
    assert invalid(_coordinate, bad, "mapy", 90)["reason"] == "invalid_coordinate"


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "sNaN"])
def test_coordinate_non_finite(bad):
    # NaN/Infinity는 반드시 BusinessException이어야 한다(다른 예외면 건별 실패 처리를 우회).
    extra = invalid(_coordinate, bad, "mapy", 90)
    assert extra["field"] == "mapy"


def test_coordinate_unsupported_types():
    invalid(_coordinate, [1], "mapy", 90)
    invalid(_coordinate, {"a": 1}, "mapy", 90)


def test_coordinate_zero_zero_accepted_documented():
    # 0은 유효 범위라 통과한다(한국 밖 좌표지만 걸러 내지 않음).
    assert _coordinate("0", "mapy", 90) == 0


# ---- _category ----
@pytest.mark.parametrize("code,name", [
    ("EV010100", "축제"), ("EV010500", "계절행사"), ("EV01", "축제"), ("EV010501", "축제"),
    ("EV020100", "공연"), ("EV030100", "전시"), ("EV030200", "체험"), ("EV03", "체험"),
])
def test_category_ok(code, name):
    assert _category(code) == name


@pytest.mark.parametrize("code", ["", "EV04", "ev010100", "XX010100", "EV0", "AA"])
def test_category_unknown(code):
    extra = invalid(_category, code)
    assert extra["reason"] == "unknown_category" and extra["value"] == code


# ---- _fee ----
@pytest.mark.parametrize("text,expected", [
    (None, (None, None)),
    ("", (None, None)),
    ("무료", (0, True)),
    ("전편 무료 관람", (0, True)),
    ("입장료 없음", (0, True)),
    ("입장료  없음", (0, True)),
    ("0원", (0, True)),
    ("성인 0원 / 어린이 0원", (0, True)),
    ("5,000원", (5000, False)),
    ("성인 10,000원 어린이 5,000원", (5000, False)),
    ("1,000원~5,000원", (1000, False)),
    ("유료", (None, False)),
    ("유료 (현장 문의)", (None, False)),
    ("현장 문의", (None, None)),
    ("1만원", (None, None)),
    ("무료 (일부 유료 체험 3,000원)", (3000, False)),
    ("무료입장 / 체험 2000 원", (2000, False)),
    ("0원 (유료 체험 별도)", (0, False)),
])
def test_fee(text, expected):
    assert _fee(text) == expected


def test_fee_price_overflow():
    assert _fee("2,147,483,647원") == (2147483647, False)
    assert invalid(_fee, "2,147,483,648원")["reason"] == "price_out_of_range"


def test_fee_free_for_children_but_paid_adult():
    # 어린이 무료 + 성인 5,000원: 금액이 있으므로 유료/최소 5000으로 본다(최소값은 0이 아님).
    assert _fee("어린이 무료, 성인 5,000원") == (5000, False)


# ---- _homepage_url ----
@pytest.mark.parametrize("raw,expected", [
    (None, None),
    ("", None),
    ("https://example.com", "https://example.com"),
    ("http://example.com/a?b=1", "http://example.com/a?b=1"),
    ("www.example.com", "https://www.example.com"),
    ("example.co.kr/path", "https://example.co.kr/path"),
    ('<a href="https://example.com/x?a=1&amp;b=2" target="_blank">홈</a>', "https://example.com/x?a=1&b=2"),
    ("<a href='http://a.com'>x</a>", "http://a.com"),
    ("자세한 내용은 https://example.com. 참고", "https://example.com"),
    ("(https://example.com/a)", "https://example.com/a"),
    ("https://a.com https://b.com", "https://a.com"),
    ("홈페이지 없음", None),
    ("localhost", None),
    ("http://localhost:8080", None),
    ("ftp://example.com", None),
    ("https://user:pw@example.com", None),
    ("https://example.com:99999", None),
])
def test_homepage_url(raw, expected):
    assert _homepage_url(raw) == expected


def test_homepage_email_not_url():
    assert _homepage_url("문의 info@example.com") is None


def test_homepage_javascript_href_rejected():
    assert _homepage_url('<a href="javascript:alert(1)">x</a>') is None


def test_homepage_protocol_relative_keeps_host():
    assert _homepage_url("//cdn.example.com/x") == "https://cdn.example.com/x"
