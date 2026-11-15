"""웹서버 프로세스 안에서 하루 한 번 KOPIS 공연을 수집하는 스케줄러.

동작은 tour.scheduler.SyncScheduler와 같고, 마지막 전체 성공 시각은 tour_sync_state의 id=2 행에 둔다.
KOPIS_API_KEY가 없으면 시작하지 않는다.
"""

from datetime import timedelta

from app.core.errors import ErrorCode
from app.domains.kopis.sync_service import KopisSyncService
from app.domains.tour.scheduler import SyncScheduler

STATE_ID = 2
SYNC_INTERVAL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(hours=6)


class KopisSyncScheduler(SyncScheduler):
    """KOPIS 공연을 24시간 주기로 수집한다. 실패하면 6시간 뒤 다시 시도한다."""

    name = "kopis-sync"
    state_id = STATE_ID
    interval = SYNC_INTERVAL
    retry_interval = RETRY_INTERVAL
    config_key = "KOPIS_API_KEY"
    incomplete_error = ErrorCode.KOPIS_SYNC_INCOMPLETE
    failed_error = ErrorCode.KOPIS_SYNC_SCHEDULE_FAILED

    def sync(self):
        return KopisSyncService().sync_performances()

    def log_success(self, app, report):
        app.logger.info(
            "공연 자동 갱신 완료: 신규 %s건, 갱신 %s건, 제외 %s건, TourAPI 중복 %s건",
            report["saved"], report["updated"], report["skipped"], len(report["duplicates"]),
        )


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
kopis_sync_scheduler = KopisSyncScheduler()
