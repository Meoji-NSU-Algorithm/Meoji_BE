"""서비스 전반에서 공유하는 시간대 상수."""
from datetime import timedelta, timezone

# 한국 표준시(UTC+9). 행사 기간과 조회수 집계 날짜는 이 시간대를 기준으로 계산한다.
KST = timezone(timedelta(hours=9))
