
"""길찾기 외부 API 응답을 처리할 때 사용하는 유틸리티."""

import math


def valid_number_or_none(value):
    """0 이상의 유한한 숫자만 반환하고, 잘못된 값은 None으로 반환한다."""
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        return None

    return value
