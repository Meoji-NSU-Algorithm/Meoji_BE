
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
        current_app.logger.warning(
            "%s 길찾기 API 요청 시간 초과",
            provider,
        )
        raise BusinessException(
            ErrorCode.DIRECTIONS_API_TIMEOUT
        ) from None

    except requests.HTTPError as error:
        # 서비스별 HTTP 오류 처리가 필요한 경우 콜백에 위임한다.
        if on_http_error is not None:
            on_http_error(error)

        current_app.logger.warning(
            "%s 길찾기 API HTTP 오류",
            provider,
        )
        raise BusinessException(
            ErrorCode.DIRECTIONS_API_ERROR
        ) from None

    except (requests.RequestException, ValueError):
        current_app.logger.warning(
            "%s 길찾기 API 호출 실패",
            provider,
        )
        raise BusinessException(
            ErrorCode.DIRECTIONS_API_ERROR
        ) from None
