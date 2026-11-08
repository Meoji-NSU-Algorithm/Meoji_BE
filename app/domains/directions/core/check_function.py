"""공통 숫자 검증 기능을 담당한다."""

import math


def number_or_none(value):
    """올바른 숫자이면 반환하고, 아니면 None을 반환한다."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        return None

    return value