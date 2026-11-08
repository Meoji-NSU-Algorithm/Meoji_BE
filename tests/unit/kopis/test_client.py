"""KopisAPI 테스트. fixtures는 2026-11-08에 받은 실제 응답이다."""
from datetime import date
from unittest.mock import MagicMock

import pytest
import requests

from app.core.errors import BusinessException, ErrorCode
from app.domains.kopis import client as kc
from app.domains.kopis.client import KopisAPI

from .conftest import fixture_bytes

ERROR_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><dbs><db><returncode>{code}</returncode>'
    "<errmsg>{msg}</errmsg></db></dbs>"
)


def api_with(*contents):
    session = MagicMock()
    responses = []
    for content in contents:
        r = MagicMock()
        r.content = content
        responses.append(r)
    session.get.side_effect = responses
    return KopisAPI(service_key="k", session=session, sleep=lambda s: None), session


def test_missing_key(app_ctx):
    app_ctx.config["KOPIS_API_KEY"] = None
    with pytest.raises(BusinessException) as e:
        KopisAPI()
    assert e.value.error_code == ErrorCode.KOPIS_API_KEY_MISSING


def test_list_page_parsed_and_stops_on_short_page():
    api, session = api_with(fixture_bytes("list.xml"))
    pages = list(api.iter_performances(date(2026, 11, 8), date(2026, 12, 8)))
    assert len(pages) == 1 and pages[0][0] == 1
    item = pages[0][1][0]
    assert item["mt20id"] == "PF305686" and item["prfpdfrom"] == "2026.11.28"
    assert item["area"] == "대구광역시" and item["genrenm"] == "연극"
    assert item["poster"].endswith(".png")
    params = session.get.call_args.kwargs["params"]
    assert params == {"service": "k", "stdate": "20261108", "eddate": "20261208", "cpage": 1, "rows": kc.ROWS}


def test_list_pages_until_short(monkeypatch):
    monkeypatch.setattr(kc, "ROWS", 5)
    nodata = ERROR_XML.format(code="04", msg="NODATA ERROR").encode()
    api, session = api_with(fixture_bytes("list.xml"), nodata)  # 5건(가득) 뒤 NODATA
    pages = list(api.iter_performances(date(2026, 11, 8), date(2026, 12, 8)))
    assert [p for p, _ in pages] == [1] and session.get.call_count == 2


def test_detail_and_facility():
    api, _ = api_with(fixture_bytes("detail.xml"), fixture_bytes("facility.xml"))
    detail = api.performance("PF305686")
    assert detail["mt10id"] == "FC001828" and detail["pcseguidance"] == "전석 30,000원"
    assert detail["relateurl"].startswith("https://www.nanumticket.or.kr/")
    assert "&amp;" not in detail["relateurl"]
    assert detail["sty"] is None  # 공백뿐인 값은 None
    facility = api.facility("FC001828")
    assert (facility["la"], facility["lo"]) == ("35.855709600000000", "128.58320249999997")


def test_api_error_code_raises_without_key_in_extra():
    api, _ = api_with(ERROR_XML.format(code="02", msg="SERVICE KEY IS NOT REGISTERED ERROR").encode())
    with pytest.raises(BusinessException) as e:
        api.performance("PF1")
    assert e.value.error_code == ErrorCode.KOPIS_REQUEST_FAILED
    assert e.value.extra["returncode"] == "02" and "k" not in e.value.extra.values()


def test_not_found_detail():
    api, _ = api_with(ERROR_XML.format(code="04", msg="NODATA ERROR").encode())
    with pytest.raises(BusinessException) as e:
        api.performance("PF0")
    assert e.value.error_code == ErrorCode.KOPIS_INVALID_RESPONSE


def test_not_xml():
    api, _ = api_with(b"<html>oops")
    with pytest.raises(BusinessException) as e:
        api.facility("FC1")
    assert e.value.extra["reason"] == "not_xml"


@pytest.mark.parametrize("effect, reason", [(requests.Timeout(), "timeout"), (requests.ConnectionError(), "connection_error")])
def test_request_errors(effect, reason):
    session = MagicMock()
    session.get.side_effect = effect
    with pytest.raises(BusinessException) as e:
        KopisAPI(service_key="k", session=session, sleep=lambda s: None).facility("FC1")
    assert e.value.extra["reason"] == reason and e.value.__cause__ is None


def test_delay_between_requests_not_before_first():
    sleeps = []
    session = MagicMock()
    r = MagicMock()
    r.content = fixture_bytes("facility.xml")
    session.get.return_value = r
    api = KopisAPI(service_key="k", session=session, sleep=sleeps.append)
    api.facility("FC1")
    api.facility("FC2")
    assert sleeps == [kc.REQUEST_DELAY_SECONDS]


def test_http_error_keeps_api_error_body():
    r = MagicMock()
    r.status_code = 400
    r.content = ERROR_XML.format(code="99", msg="TOO MANY").encode()
    r.raise_for_status.side_effect = requests.HTTPError()
    session = MagicMock()
    session.get.return_value = r
    with pytest.raises(BusinessException) as e:
        KopisAPI(service_key="k", session=session, sleep=lambda s: None).facility("FC1")
    assert e.value.extra == {"reason": "http_error", "status": 400, "path": "prfplc/FC1", "returncode": "99", "errmsg": "TOO MANY"}
