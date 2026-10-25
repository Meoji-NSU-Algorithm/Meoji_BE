"""한국관광공사 KorService2 API 클라이언트.

축제 목록과 상세를 조회하고 응답 구조를 검증한다. DB 저장과 분류 변환은
sync_service가 맡는다.
"""

import re
from collections.abc import Iterator
from datetime import datetime, timedelta

import requests
from flask import current_app
from app.core.errors import BusinessException, ErrorCode
from app.core.time import KST


class TourAPI:
    """searchFestival2, detailCommon2, detailIntro2만 사용하는 축제 전용 클라이언트."""

    def __init__(self, service_key: str | None = None):
        """클라이언트를 만든다.

        Args:
            service_key: TourAPI 인증키. 생략하면 current_app.config["TOURAPI_KEY"]를
                사용하므로 앱 컨텍스트가 필요하다.

        Raises:
            BusinessException: 키가 없으면 TOUR_API_KEY_MISSING.
        """
        if service_key is None:
            service_key = current_app.config.get("TOURAPI_KEY")
        if not service_key:
            raise BusinessException(ErrorCode.TOUR_API_KEY_MISSING)
        # 키가 URL 인코딩된 형태로 설정될 수 있다. 한 번 풀어 두어야 requests가 쿼리를
        # 인코딩할 때 이중 인코딩되지 않는다.
        self.api_key = requests.utils.unquote(service_key)
        self.api_base_url = "https://apis.data.go.kr/B551011/KorService2"
        self.default_params = {
            "serviceKey": self.api_key,
            "MobileOS": "ETC",
            "MobileApp": "CheonanOn",
            "_type": "json",
        }

    def request(self, endpoint: str, params: dict | None = None) -> dict:
        """엔드포인트를 한 번 호출하고 응답의 body를 반환한다.

        Raises:
            BusinessException: 통신 실패와 resultCode 오류는 TOUR_API_REQUEST_FAILED
                (extra.reason: timeout, http_error, connection_error, api_result),
                응답 구조 이상은 TOUR_API_INVALID_RESPONSE.
        """
        try:
            response = requests.get(
                f"{self.api_base_url}/{endpoint}",
                params={**self.default_params, **(params or {})},
                timeout=10,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "timeout"}) from error
        except requests.exceptions.HTTPError as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "http_error"}) from error
        except requests.exceptions.RequestException as error:
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "connection_error"}) from error

        # HTTP 200이어도 JSON 구조가 깨져 있을 수 있다.
        try:
            data = response.json()
            api_response = data["response"]
            header = api_response["header"]
            if not isinstance(header, dict):
                raise ValueError("header 형식")
        except (ValueError, TypeError, KeyError) as error:
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE) from error
        # 공공데이터 API는 실패도 HTTP 200으로 내려주고 resultCode로 알린다.
        if str(header.get("resultCode")) != "0000":
            raise BusinessException(ErrorCode.TOUR_API_REQUEST_FAILED, extra={"reason": "api_result", "result_code": str(header.get("resultCode"))})
        # 실패 응답에는 body가 없을 수 있어 성공 코드를 확인한 뒤에 읽는다.
        body = api_response.get("body")
        if not isinstance(body, dict):
            raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
        return body

    @staticmethod
    def get_items(body: dict) -> list[dict]:
        """body에서 item 목록을 꺼내 항상 list[dict]로 반환한다."""
        # TourAPI는 0건이면 items를 빈 문자열로, 1건이면 item을 객체 하나로 내려준다.
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
        """조회 기간을 검증해 (시작일, 종료일) YYYYMMDD 문자열로 반환한다.

        둘 다 생략하면 KST 기준 7일 전부터, 종료일 없이 조회한다. 최근 등록·수정된
        행사를 놓치지 않고 먼 미래 행사도 포함하기 위해서다.

        Raises:
            BusinessException: TOUR_FESTIVAL_INVALID_PERIOD(시작일 누락, 형식 오류,
                없는 날짜, 시작일이 종료일보다 늦음).
        """
        if start_date is None and end_date is None:
            today = datetime.now(KST).date()
            return (today - timedelta(days=7)).strftime("%Y%m%d"), None
        if start_date is None:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "start_date_required"})
        start_date = str(start_date)
        end_date = str(end_date) if end_date is not None else None
        if not re.fullmatch(r"[0-9]{8}", start_date) or (end_date is not None and not re.fullmatch(r"[0-9]{8}", end_date)):
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "invalid_date_format"})
        # 20260230처럼 8자리여도 달력에 없는 날짜가 있다.
        try:
            start = datetime.strptime(start_date, "%Y%m%d")
            end = datetime.strptime(end_date, "%Y%m%d") if end_date is not None else None
        except ValueError as error:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "invalid_calendar_date"}) from error
        if end is not None and start > end:
            raise BusinessException(ErrorCode.TOUR_FESTIVAL_INVALID_PERIOD, extra={"reason": "start_after_end"})
        return start_date, end_date

    def iter_festivals(self, start_date: str | None = None, end_date: str | None = None) -> Iterator[tuple[int, list[dict]]]:
        """전국 축제 목록을 페이지 단위로 `(page, items)`씩 내보낸다.

        lDongRegnCd를 보내지 않아 전국을 조회한다. 제너레이터라 목록 전체를 메모리에
        쌓지 않는다.

        Raises:
            BusinessException: 기간 오류, 또는 페이징 응답이 비정상이면
                TOUR_API_INVALID_RESPONSE(totalCount 비정상·변경, 같은 페이지 반복,
                총건수와 수신 건수 불일치).
        """
        start_date, end_date = self.validate_festival_dates(start_date, end_date)
        page, received, expected, fingerprints = 1, 0, None, set()
        while True:
            # arrange=A(제목순)로 정렬을 고정해 페이지 간 중복·누락을 줄인다.
            params = {
                "eventStartDate": start_date,
                "arrange": "A",
                "pageNo": page,
                "numOfRows": 100,
            }
            # 종료일은 호출자가 지정했을 때만 보낸다.
            if end_date is not None:
                params["eventEndDate"] = end_date
            body = self.request("searchFestival2", params)
            rows = self.get_items(body)
            # totalCount가 비정상이거나 수집 중 바뀌면 일부만 받고 성공으로 오인할 수 있어 중단한다.
            total_text = str(body.get("totalCount", ""))
            if not re.fullmatch(r"[0-9]+", total_text):
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
            total = int(total_text)
            if expected is not None and total != expected:
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE, extra={"reason": "total_count_changed", "page": page})
            expected = total
            # API가 같은 페이지를 반복해 돌려주면 무한 루프가 되므로 막는다.
            fingerprint = repr(rows)
            if rows and fingerprint in fingerprints:
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE, extra={"reason": "repeated_page", "page": page})
            fingerprints.add(fingerprint)
            # 남은 데이터가 있는데 빈 페이지가 오거나 총건수를 넘으면 오류다.
            received += len(rows)
            if received > total or (not rows and received < total):
                raise BusinessException(ErrorCode.TOUR_API_INVALID_RESPONSE)
            yield page, rows
            if received == total:
                return
            page += 1

    def _one_detail(self, endpoint: str, content_id: str | int, intro: bool = False) -> dict:
        """contentId 한 건의 상세 row를 반환한다. intro 엔드포인트는 contentTypeId=15(축제)가 필요하다."""
        params = {"contentId": str(content_id), "pageNo": 1, "numOfRows": 10}
        if intro:
            params["contentTypeId"] = 15
        rows = self.get_items(self.request(endpoint, params))
        # 0건이거나 여러 건이면 어느 값을 저장할지 알 수 없어 실패 처리한다.
        if len(rows) != 1:
            raise BusinessException(ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"reason": "detail_count", "endpoint": endpoint})
        row = rows[0]
        if "contentid" in row and str(row["contentid"]) != str(content_id):
            raise BusinessException(ErrorCode.TOUR_SYNC_ID_MISMATCH)
        return row

    def festival_common(self, content_id: str | int) -> dict:
        """detailCommon2의 공통 상세(overview, 홈페이지, 주소, 이미지 등)를 반환한다."""
        return self._one_detail("detailCommon2", content_id)

    def festival_intro(self, content_id: str | int) -> dict:
        """detailIntro2의 축제 상세(장소, 시간, 요금, 주최 등)를 반환한다."""
        return self._one_detail("detailIntro2", content_id, intro=True)
