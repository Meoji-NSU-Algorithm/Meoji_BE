"""공연예술통합전산망(KOPIS) OpenAPI 클라이언트.

공연 목록(pblprfr), 공연 상세(pblprfr/{id}), 공연시설 상세(prfplc/{id})만 쓴다.
응답은 XML이고, 오류도 HTTP 200에 <returncode>로 온다(02: 키 오류, 04: 데이터 없음).
DB 저장과 분류 변환은 sync_service가 맡는다.
"""

import time
import xml.etree.ElementTree as ET

import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode

# 인증키가 쿼리에 실리므로 https로 보낸다(www. 주소는 301로 이 주소에 보낸다).
BASE_URL = "https://kopis.or.kr/openApi/restful"
ROWS = 100  # 목록 한 페이지 최대 건수
MAX_PAGES = 100  # 페이지 끝을 못 찾아도 멈추도록 상한을 둔다(1개월 전국 약 23페이지).
TIMEOUT_SECONDS = 15
# 공식 한도 수치는 공개돼 있지 않다(초과 시 키 사용 중지). 0.2초 간격에서 HTTP 400 차단이 나 늘렸다.
REQUEST_DELAY_SECONDS = 0.6


def _fields(db_node):
    """<db> 아래 단일 값 태그를 {태그: 앞뒤 공백 뺀 문자열}로. 빈 값은 None."""
    return {child.tag: ((child.text or "").strip() or None) for child in db_node if len(child) == 0}


def _error_body(response):
    """오류 응답 본문의 returncode·errmsg. XML이 아니면 빈 dict(본문에 키가 섞일 수 있어 원문은 남기지 않는다)."""
    try:
        node = ET.fromstring(response.content).find("db")
    except (ET.ParseError, TypeError):
        return {}
    if node is None:
        return {}
    return {"returncode": node.findtext("returncode"), "errmsg": node.findtext("errmsg")}


class KopisAPI:
    """service_key와 session은 테스트 주입용이다. 생략하면 KOPIS_API_KEY 설정을 쓴다."""

    def __init__(self, service_key=None, session=None, sleep=time.sleep):
        if service_key is None:
            service_key = current_app.config.get("KOPIS_API_KEY")
        if not service_key:
            raise BusinessException(ErrorCode.KOPIS_API_KEY_MISSING)
        self.service_key = service_key
        self.session = session or requests.Session()
        self._sleep = sleep
        self._requested = False

    def _get(self, path, params=None):
        """한 번 호출하고 <db> 노드 목록을 반환한다. NODATA(04)는 빈 목록이다."""
        if self._requested:
            self._sleep(REQUEST_DELAY_SECONDS)
        self._requested = True
        # requests 예외 메시지에는 키가 담긴 URL이 있어 `from None`으로 원인 연결을 끊는다.
        try:
            response = self.session.get(
                f"{BASE_URL}/{path}",
                params={"service": self.service_key, **(params or {})},
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.Timeout:
            raise BusinessException(ErrorCode.KOPIS_REQUEST_FAILED, extra={"reason": "timeout", "path": path}) from None
        except requests.HTTPError:
            raise BusinessException(
                ErrorCode.KOPIS_REQUEST_FAILED,
                extra={"reason": "http_error", "status": response.status_code, "path": path, **_error_body(response)},
            ) from None
        except requests.RequestException:
            raise BusinessException(ErrorCode.KOPIS_REQUEST_FAILED, extra={"reason": "connection_error", "path": path}) from None
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            raise BusinessException(ErrorCode.KOPIS_INVALID_RESPONSE, extra={"reason": "not_xml", "path": path}) from None
        nodes = root.findall("db")
        code = nodes[0].findtext("returncode") if nodes else None
        if code == "04":
            return []
        if code is not None:
            raise BusinessException(
                ErrorCode.KOPIS_REQUEST_FAILED,
                extra={"reason": "api_result", "returncode": code, "errmsg": nodes[0].findtext("errmsg"), "path": path},
            )
        return nodes

    def iter_performances(self, start_date, end_date):
        """기간과 겹치는 공연 목록을 (page, items)로 내보낸다. 날짜는 date."""
        for page in range(1, MAX_PAGES + 1):
            nodes = self._get("pblprfr", {
                "stdate": start_date.strftime("%Y%m%d"),
                "eddate": end_date.strftime("%Y%m%d"),
                "cpage": page,
                "rows": ROWS,
            })
            if nodes:
                yield page, [_fields(node) for node in nodes]
            if len(nodes) < ROWS:
                return
        raise BusinessException(ErrorCode.KOPIS_INVALID_RESPONSE, extra={"reason": "too_many_pages", "limit": MAX_PAGES})

    def _one(self, path):
        nodes = self._get(path)
        if not nodes:
            raise BusinessException(ErrorCode.KOPIS_INVALID_RESPONSE, extra={"reason": "not_found", "path": path})
        return _fields(nodes[0])

    def performance(self, performance_id):
        """공연 상세. 예매 링크(relateurl)는 여러 개라 첫 번째만 relateurl로 넣는다."""
        nodes = self._get(f"pblprfr/{performance_id}")
        if not nodes:
            raise BusinessException(ErrorCode.KOPIS_INVALID_RESPONSE, extra={"reason": "not_found", "id": performance_id})
        detail = _fields(nodes[0])
        detail["relateurl"] = nodes[0].findtext("relates/relate/relateurl")
        return detail

    def facility(self, facility_id):
        """공연시설 상세(주소, 전화, 위도 la, 경도 lo)."""
        return self._one(f"prfplc/{facility_id}")
