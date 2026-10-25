# 한국관광공사 KorService2에서 전국 행사 목록과 축제 상세를 조회한다.
# 이 파일은 HTTP 요청·응답 검증만 담당한다. DB 저장과 분류 변환은
# tour_sync.py에 있으므로 API 조회만 하고 싶을 때도 이 클래스를 쓸 수 있다.

import re
from collections.abc import Iterator
from datetime import datetime, timedelta

import requests
from flask import current_app
from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST


class TourAPI:
    # searchFestival2 / detailCommon2 / detailIntro2만 사용하는 축제 전용 클라이언트.

    def __init__(self, service_key: str | None = None):
        # 키를 직접 넘기지 않으면 앱 설정에서 읽는다(앱 컨텍스트 필요).
        if service_key is None:
            service_key = current_app.config.get("TOURAPI_KEY")
        # 키가 없으면 외부 요청 전에 실패시켜 설정 누락을 바로 알 수 있게 한다.
        if not service_key:
            raise BusinessException(ErrorCode.TOUR_API_KEY_MISSING)
        # 이미 URL 인코딩된 키를 requests가 다시 인코딩하지 않도록 한 번 푼다.
        self.api_key = requests.utils.unquote(service_key)
        self.api_base_url = "https://apis.data.go.kr/B551011/KorService2"  # API 공통 주소
        # 모든 엔드포인트가 요구하는 인증 키·클라이언트 정보·JSON 응답 형식.
        self.default_params = {
            "serviceKey": self.api_key,
            "MobileOS": "ETC",
            "MobileApp": "CheonanOn",
            "_type": "json",
        }

    def request(self, endpoint: str, params: dict | None = None) -> dict:
        # 호출별 파라미터를 기본 파라미터와 합쳐 한 번 요청한다.
        # 연결/타임아웃/HTTP 실패를 공통 ErrorCode와 extra.reason으로 전달한다.
        try:
            response = requests.get(
                f"{self.api_base_url}/{endpoint}",
                params={**self.default_params, **(params or {})},
                timeout=10,
            )
            response.raise_for_status()  # HTTP 4xx/5xx를 예외로 바꿈
        except requests.exceptions.Timeout as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "timeout"}) from error
        except requests.exceptions.HTTPError as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "http_error"}) from error
        except requests.exceptions.RequestException as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "connection_error"}) from error

        # 정상 HTTP 응답이어도 JSON 구조가 깨져 있으면 저장을 진행하면 안 된다.
        try:
            data = response.json()
            api_response = data["response"]
            header = api_response["header"]
            if not isinstance(header, dict):
                raise ValueError("header 형식")
        except (ValueError, TypeError, KeyError) as error:
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE) from error
        # 공공데이터 API는 HTTP 200이어도 resultCode로 실패를 알릴 수 있다.
        if str(header.get("resultCode")) != "0000":
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "api_result", "result_code": str(header.get("resultCode"))})
        # 실패 응답은 body가 없을 수 있으므로 성공 코드를 확인한 뒤 body를 읽는다.
        body = api_response.get("body")
        if not isinstance(body, dict):
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
        return body

    @staticmethod
    def get_items(body: dict) -> list[dict]:
        # TourAPI는 0건이면 items를 빈 문자열로, 1건이면 item 객체 하나로 줄 수 있다.
        # 호출자가 항상 list[dict]로 처리할 수 있게 반환 형식을 통일한다.
        items = body.get("items", "")
        if not items:
            return []
        if not isinstance(items, dict):
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
        rows = items.get("item", [])
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
        return rows

    @staticmethod
    def validate_festival_dates(start_date: str | None = None, end_date: str | None = None) -> tuple[str, str | None]:
        # 기간을 생략하면 한국 시간 기준 7일 전부터 조회한다. 최근에 등록·수정된
        # 행사를 놓칠 가능성을 줄이고, 종료일은 생략해 먼 미래의 행사도 포함한다.
        if start_date is None and end_date is None:
            today = datetime.now(KST).date()
            return (today - timedelta(days=7)).strftime("%Y%m%d"), None
        if start_date is None:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "start_date_required"})
        start_date = str(start_date)
        end_date = str(end_date) if end_date is not None else None
        if not re.fullmatch(r"[0-9]{8}", start_date) or (end_date is not None and not re.fullmatch(r"[0-9]{8}", end_date)):
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "invalid_date_format"})
        # 8자리 숫자라도 20260230처럼 실제 달력에 없는 날짜는 거부한다.
        try:
            start = datetime.strptime(start_date, "%Y%m%d")
            end = datetime.strptime(end_date, "%Y%m%d") if end_date is not None else None
        except ValueError as error:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "invalid_calendar_date"}) from error
        if end is not None and start > end:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "start_after_end"})
        return start_date, end_date

    def iter_festivals(self, start_date: str | None = None, end_date: str | None = None) -> Iterator[tuple[int, list[dict]]]:
        # lDongRegnCd를 보내지 않아 전국을 조회한다. 제너레이터라 페이지를
        # 받는 즉시 저장 서비스가 처리할 수 있고 목록 전체를 메모리에 쌓지 않는다.
        start_date, end_date = self.validate_festival_dates(start_date, end_date)
        page, received, expected, fingerprints = 1, 0, None, set()  # 페이지/누적/기대 건수/반복 감지
        while True:
            # TourAPI의 한 페이지 최대 100건을 요청하고 정렬을 고정한다.
            params = {
                "eventStartDate": start_date,
                "arrange": "A",
                "pageNo": page,
                "numOfRows": 100,
            }
            # 종료일을 명시한 범위 조회에서만 전송한다. 기본 수집은 7일 전부터
            # 이후의 모든 행사를 조회하고, 저장 단계에서 이미 끝난 행사를 거른다.
            if end_date is not None:
                params["eventEndDate"] = end_date
            body = self.request("searchFestival2", params)
            rows = self.get_items(body)
            # totalCount가 숫자가 아니거나 수집 도중 변하면 일부만 받아도
            # 성공으로 보고할 위험이 있으므로 중단한다.
            total_text = str(body.get("totalCount", ""))
            if not re.fullmatch(r"[0-9]+", total_text):
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
            total = int(total_text)
            if expected is not None and total != expected:
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE, extra={"reason": "total_count_changed", "page": page})
            expected = total
            # API가 같은 페이지를 반복해서 반환하면 무한 루프가 되지 않도록 막는다.
            fingerprint = repr(rows)
            if rows and fingerprint in fingerprints:
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE, extra={"reason": "repeated_page", "page": page})
            fingerprints.add(fingerprint)
            # 남은 데이터가 있는데 빈 페이지가 나오거나 총건수를 넘는 응답도 오류다.
            received += len(rows)
            if received > total or (not rows and received < total):
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
            yield page, rows
            if received == total:
                return
            page += 1

    def _one_detail(self, endpoint: str, content_id: str | int, intro: bool = False) -> dict:
        # contentId 한 건의 상세만 요청한다. intro는 contentTypeId=15가 필요하다.
        params = {"contentId": str(content_id), "pageNo": 1, "numOfRows": 10}
        if intro:
            params["contentTypeId"] = 15
        rows = self.get_items(self.request(endpoint, params))
        # 상세가 없거나 여러 건이면 어느 값을 저장해야 할지 알 수 없으므로 실패.
        if len(rows) != 1:
            raise BusinessException(ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"reason": "detail_count", "endpoint": endpoint})
        row = rows[0]
        if "contentid" in row and str(row["contentid"]) != str(content_id):
            raise BusinessException(ErrorCode.TOUR_SYNC_ID_MISMATCH)
        return row

    def festival_common(self, content_id: str | int) -> dict:
        # detailCommon2: overview, 홈페이지, 주소, 이미지 등 공통 상세.
        return self._one_detail("detailCommon2", content_id)

    def festival_intro(self, content_id: str | int) -> dict:
        # detailIntro2: 행사 장소, 시간, 요금, 주최 등 축제 상세.
        return self._one_detail("detailIntro2", content_id, intro=True)
