"""서비스 전반에서 공유하는 시간대 상수와 UTC 현재 시각 함수."""
from datetime import datetime, timedelta, timezone

# 한국 표준시(UTC+9). 행사 기간과 조회수 집계 날짜는 이 시간대를 기준으로 계산한다.
KST = timezone(timedelta(hours=9))


def utcnow() -> datetime:
    """현재 시각을 UTC(시간대 정보 포함)로 반환한다. DB 저장 시각과 동의 시각에 쓴다."""
    return datetime.now(timezone.utc)
