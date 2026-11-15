"""외부 길찾기 API 요청을 공통으로 처리한다."""

import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode


def get_api_key(config_name):
    """설정에서 외부 API 키를 가져온다."""

    api_key = current_app.config.get(config_name)

    if not api_key:
        raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

    return api_key


def request_json(url, params, headers=None):
    """외부 API를 호출하고 JSON 응답을 반환한다."""

    try:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=10,
        )
        response.raise_for_status()
        result = response.json()

    except requests.Timeout:
        raise BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT)

    except (requests.RequestException, ValueError):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    if not isinstance(result, dict):
        raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

    return result