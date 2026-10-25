"""TourAPI 클라이언트 테스트. requests.get은 모두 mock."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST
from app.domains.tour.client import TourAPI


def resp(payload=None, status=200, json_error=None):
    r = MagicMock()
    if status >= 400:
        r.raise_for_status.side_effect = requests.exceptions.HTTPError(f"{status}")
    else:
        r.raise_for_status.return_value = None
    if json_error:
        r.json.side_effect = json_error
    else:
        r.json.return_value = payload
    return r


def ok(body, code="0000"):
    return {"response": {"header": {"resultCode": code, "resultMsg": "x"}, "body": body}}


@pytest.fixture()
def api():
    return TourAPI("key%2Bvalue")


def code_of(exc_info):
    return exc_info.value.error_code


# ---- 키 ----
def test_explicit_key_is_unquoted(api):
    assert api.api_key == "key+value"
    assert api.default_params["serviceKey"] == "key+value"


def test_missing_key_explicit_empty(app_ctx):
    with pytest.raises(BusinessException) as e:
        TourAPI("")
    assert code_of(e) == ErrorCode.TOUR_API_KEY_MISSING


def test_key_from_config(app_ctx):
    assert TourAPI().api_key == "test-tourapi-key"


def test_missing_key_from_config(app_ctx):
    app_ctx.config["TOURAPI_KEY"] = None
    try:
        with pytest.raises(BusinessException) as e:
            TourAPI()
        assert code_of(e) == ErrorCode.TOUR_API_KEY_MISSING
    finally:
        app_ctx.config["TOURAPI_KEY"] = "test-tourapi-key"


# ---- request ----
def test_request_success_returns_body(api):
    with patch("requests.get", return_value=resp(ok({"totalCount": 0, "items": ""}))) as g:
        body = api.request("searchFestival2", {"pageNo": 2})
    assert body["totalCount"] == 0
    kwargs = g.call_args.kwargs
    assert kwargs["timeout"] == 10
    assert kwargs["params"]["pageNo"] == 2 and kwargs["params"]["serviceKey"] == "key+value"
    assert g.call_args.args[0].endswith("/searchFestival2")


@pytest.mark.parametrize("exc,reason", [
    (requests.exceptions.Timeout(), "timeout"),
    (requests.exceptions.ConnectTimeout(), "timeout"),
    (requests.exceptions.ConnectionError(), "connection_error"),
    (requests.exceptions.TooManyRedirects(), "connection_error"),
])
def test_request_transport_errors(api, exc, reason):
    with patch("requests.get", side_effect=exc):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_REQUEST_FAILED
    assert e.value.extra["reason"] == reason


@pytest.mark.parametrize("status", [500, 502, 503, 404])
def test_request_http_error(api, status):
    with patch("requests.get", return_value=resp(status=status)):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_REQUEST_FAILED
    assert e.value.extra["reason"] == "http_error"


@pytest.mark.parametrize("result_code", ["0001", "0030", "99", 1, None])
def test_request_failing_result_code(api, result_code):
    payload = {"response": {"header": {"resultCode": result_code, "resultMsg": "bad"}}}
    with patch("requests.get", return_value=resp(payload)):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_REQUEST_FAILED
    assert e.value.extra["reason"] == "api_result"
    assert e.value.extra["result_code"] == str(result_code)


def test_result_code_int_zero_string_forms(api):
    # 숫자 0은 "0"이라 "0000"이 아니므로 실패로 본다(문서화).
    payload = ok({"totalCount": 0}, code=0)
    with patch("requests.get", return_value=resp(payload)):
        with pytest.raises(BusinessException):
            api.request("x")


@pytest.mark.parametrize("payload", [
    [], "text", {}, {"response": None}, {"response": {}}, {"response": {"header": "x"}},
    {"response": {"header": None}}, {"response": []},
])
def test_request_malformed_structure(api, payload):
    with patch("requests.get", return_value=resp(payload)):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


def test_request_non_json(api):
    with patch("requests.get", return_value=resp(json_error=ValueError("no json"))):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


@pytest.mark.parametrize("body", [None, "", [], "str"])
def test_request_success_with_bad_body(api, body):
    with patch("requests.get", return_value=resp(ok(body))):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


def test_response_json_raising_requests_json_error(api):
    with patch("requests.get", return_value=resp(json_error=requests.exceptions.JSONDecodeError("m", "d", 0))):
        with pytest.raises(BusinessException) as e:
            api.request("x")
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


# ---- get_items ----
def test_items_empty_string():
    assert TourAPI.get_items({"items": ""}) == []


def test_items_missing_and_none():
    assert TourAPI.get_items({}) == []
    assert TourAPI.get_items({"items": None}) == []


def test_items_single_dict():
    assert TourAPI.get_items({"items": {"item": {"a": 1}}}) == [{"a": 1}]


def test_items_list():
    assert TourAPI.get_items({"items": {"item": [{"a": 1}, {"a": 2}]}}) == [{"a": 1}, {"a": 2}]


def test_items_dict_without_item():
    assert TourAPI.get_items({"items": {}}) == []  # 빈 dict는 falsy
    assert TourAPI.get_items({"items": {"other": 1}}) == []


@pytest.mark.parametrize("items", ["abc", ["x"], 5, {"item": "x"}, {"item": [1]}, {"item": None}, {"item": ["a", {"b": 1}]}])
def test_items_invalid(items):
    with pytest.raises(BusinessException) as e:
        TourAPI.get_items({"items": items})
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


# ---- validate_festival_dates ----
def test_default_dates_use_kst_today():
    fixed = datetime(2026, 10, 25, 20, 0, tzinfo=KST)
    with patch("app.domains.tour.client.datetime") as dt:
        dt.now.return_value = fixed
        dt.strptime = datetime.strptime
        assert TourAPI.validate_festival_dates() == ("20261018", None)
        dt.now.assert_called_with(KST)


def test_default_dates_month_boundary():
    fixed = datetime(2026, 3, 3, 0, 30, tzinfo=KST)
    with patch("app.domains.tour.client.datetime") as dt:
        dt.now.return_value = fixed
        assert TourAPI.validate_festival_dates() == ("20260224", None)


def test_dates_valid():
    assert TourAPI.validate_festival_dates("20261001", "20261031") == ("20261001", "20261031")
    assert TourAPI.validate_festival_dates("20261001") == ("20261001", None)
    assert TourAPI.validate_festival_dates("20261001", "20261001") == ("20261001", "20261001")
    assert TourAPI.validate_festival_dates(20261001, 20261002) == ("20261001", "20261002")


def reason(start=None, end=None):
    with pytest.raises(BusinessException) as e:
        TourAPI.validate_festival_dates(start, end)
    assert code_of(e) == ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD
    return e.value.extra["reason"]


def test_dates_errors():
    assert reason(None, "20261001") == "start_date_required"
    assert reason("2026-10-01") == "invalid_date_format"
    assert reason("2026100") == "invalid_date_format"
    assert reason("20261001", "abc") == "invalid_date_format"
    assert reason("") == "invalid_date_format"
    assert reason("20260230") == "invalid_calendar_date"
    assert reason("20261301") == "invalid_calendar_date"
    assert reason("20261001", "20261331") == "invalid_calendar_date"
    assert reason("20261002", "20261001") == "start_after_end"


def test_dates_fullwidth_digits_rejected():
    # re의 [0-9]는 전각 숫자를 허용하지 않는다.
    assert reason("２０２６１００１") == "invalid_date_format"


def test_dates_leap_day():
    assert TourAPI.validate_festival_dates("20240229") == ("20240229", None)
    assert reason("20250229") == "invalid_calendar_date"


# ---- iter_festivals ----
def page_body(rows, total):
    return {"totalCount": total, "items": {"item": rows} if rows else ""}


def run(api, bodies, **kw):
    with patch.object(api, "request", side_effect=list(bodies)) as req:
        out = list(api.iter_festivals("20261001", **kw))
    return out, req


def test_iter_single_page(api):
    out, req = run(api, [page_body([{"a": 1}, {"a": 2}], 2)])
    assert out == [(1, [{"a": 1}, {"a": 2}])]
    params = req.call_args.args[1]
    assert params["numOfRows"] == 100 and params["arrange"] == "A" and "eventEndDate" not in params


def test_iter_end_date_sent(api):
    _, req = run(api, [page_body([{"a": 1}], 1)], end_date="20261231")
    assert req.call_args.args[1]["eventEndDate"] == "20261231"


def test_iter_multi_page(api):
    out, req = run(api, [page_body([{"a": 1}], 2), page_body([{"a": 2}], 2)])
    assert [p for p, _ in out] == [1, 2]
    assert req.call_args_list[1].args[1]["pageNo"] == 2


def test_iter_zero_results(api):
    out, _ = run(api, [page_body([], 0)])
    assert out == [(1, [])]


def test_iter_total_count_changes(api):
    with pytest.raises(BusinessException) as e:
        run(api, [page_body([{"a": 1}], 2), page_body([{"a": 2}], 3)])
    assert e.value.extra["reason"] == "total_count_changed"


@pytest.mark.parametrize("total", ["", "abc", "-1", None, "1.5"])
def test_iter_bad_total(api, total):
    body = {"items": "", "totalCount": total} if total is not None else {"items": ""}
    with pytest.raises(BusinessException) as e:
        run(api, [body])
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


def test_iter_repeated_page(api):
    with pytest.raises(BusinessException) as e:
        run(api, [page_body([{"a": 1}], 2), page_body([{"a": 1}], 2)])
    assert e.value.extra["reason"] == "repeated_page"


def test_iter_empty_page_before_total(api):
    with pytest.raises(BusinessException) as e:
        run(api, [page_body([{"a": 1}], 3), page_body([], 3)])
    assert code_of(e) == ErrorCode.TOUR_API_INVALID_RESPONSE


def test_iter_received_exceeds_total(api):
    with pytest.raises(BusinessException):
        run(api, [page_body([{"a": 1}, {"a": 2}], 1)])


def test_iter_total_zero_but_rows(api):
    with pytest.raises(BusinessException):
        run(api, [page_body([{"a": 1}], 0)])


def test_iter_invalid_period_before_request(api):
    with patch.object(api, "request") as req:
        with pytest.raises(BusinessException) as e:
            list(api.iter_festivals("bad"))
    assert code_of(e) == ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD
    req.assert_not_called()


def test_iter_propagates_request_failure(api):
    with patch("requests.get", side_effect=requests.exceptions.Timeout()):
        with pytest.raises(BusinessException) as e:
            list(api.iter_festivals("20261001"))
    assert e.value.extra["reason"] == "timeout"


# ---- detail ----
def test_detail_params_and_intro_type(api):
    with patch.object(api, "request", return_value={"items": {"item": {"contentid": "7"}}}) as req:
        assert api.festival_intro(7) == {"contentid": "7"}
        assert req.call_args.args[0] == "detailIntro2"
        assert req.call_args.args[1]["contentTypeId"] == 15
        api.festival_common(7)
        assert req.call_args.args[0] == "detailCommon2"
        assert "contentTypeId" not in req.call_args.args[1]


@pytest.mark.parametrize("items", ["", {"item": []}, {"item": [{"a": 1}, {"a": 2}]}])
def test_detail_count_not_one(api, items):
    with patch.object(api, "request", return_value={"items": items}):
        with pytest.raises(BusinessException) as e:
            api.festival_common("7")
    assert code_of(e) == ErrorCode.TOUR_SYNC_INVALID_DATA
    assert e.value.extra["reason"] == "detail_count"


def test_detail_id_mismatch(api):
    with patch.object(api, "request", return_value={"items": {"item": {"contentid": "8"}}}):
        with pytest.raises(BusinessException) as e:
            api.festival_common("7")
    assert code_of(e) == ErrorCode.TOUR_SYNC_ID_MISMATCH


def test_detail_without_contentid_accepted(api):
    with patch.object(api, "request", return_value={"items": {"item": {"overview": "x"}}}):
        assert api.festival_common("7") == {"overview": "x"}
