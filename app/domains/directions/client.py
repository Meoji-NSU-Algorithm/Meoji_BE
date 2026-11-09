
"""길찾기 외부 API(카카오모빌리티, ODsay) 통신을 담당한다."""

import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode


# 외부 길찾기 API URL
KAKAO_DIRECTIONS_URL = (
    "https://apis-navi.kakaomobility.com/v1/directions"
)
ODSAY_WALK_URL = (
    "https://api.odsay.com/v1/api/searchWalkPathV2"
)
ODSAY_TRANSIT_URL = (
    "https://api.odsay.com/v1/api/maasRP"
)

# 외부 API 공통 요청 제한 시간(초)
TIMEOUT = 10


def raise_odsay_error(result: dict, provider: str) -> None:
    """ODsay 응답 본문에 오류가 있으면 원인에 맞는 예외를 발생시킨다."""

    error = result.get("error")

    # 오류 정보가 없으면 정상 응답이므로 종료한다.
    if not error:
        return

    # 오류 정보는 리스트 또는 딕셔너리 형태로 올 수 있다.
    first = error[0] if isinstance(error, list) and error else error

    # 첫 번째 오류 정보가 딕셔너리가 아니면 빈 딕셔너리로 처리한다.
    first = first if isinstance(first, dict) else {}

    code = str(first.get("code", ""))
    message = str(first.get("message") or first.get("msg") or "")

    # ODsay API 키 인증 실패
    if "ApiKeyAuthFailed" in message:
        current_app.logger.error(
            "%s 키 인증 실패: code=%s message=%s",
            provider,
            code,
            message,
        )
        raise BusinessException(ErrorCode.DIRECTIONS_API_AUTH_FAILED) from None

    # 검색 데이터 없음 - 대중교통
    if code == "400":
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND) from None

    # 필수 정보 누락 오류 - 대중교통
    if code == "401":
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT) from None

    # 출·도착 좌표가 동일 오류 - 도보
    if code == "403":
        raise BusinessException(ErrorCode.ROUTE_NOT_FOUND) from None

    # 그 외 ODsay 오류
    current_app.logger.warning("%s 오류 응답: code=%s message=%s", provider, code, message)
    raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR) from None


def get_json(url, *, params, provider, headers=None, on_http_error=None):
    """외부 API를 호출하고 JSON 응답을 반환한다."""

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except requests.Timeout:
        current_app.logger.warning("%s 길찾기 API 요청 시간 초과", provider)
        raise BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT) from None

    except requests.HTTPError as error:
        # URL이나 예외 원문을 기록하지 않고 HTTP 상태 코드만 기록한다.
        status = (error.response.status_code if error.response is not None else None)

        current_app.logger.warning("%s 길찾기 API HTTP 오류: status=%s", provider, status)

        # 카카오 등 서비스별 HTTP 오류 처리가 필요한 경우 위임한다.
        if on_http_error is not None:
            on_http_error(error)

        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR) from None

    except (requests.RequestException, ValueError):
        current_app.logger.warning("%s 길찾기 API 호출 실패", provider)
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR) from None
