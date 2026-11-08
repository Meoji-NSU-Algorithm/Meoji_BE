"""웹서버 프로세스 안에서 하루 한 번 KOPIS 공연을 수집하는 스케줄러.

tour.scheduler.FestivalSyncScheduler와 같은 방식이다. 마지막 전체 성공 시각은
tour_sync_state의 id=2 행에 두어 재시작해도 주기가 유지된다. 시각은 모두 UTC naive다.
KOPIS_API_KEY가 없으면 시작하지 않는다.
"""

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from app.core.errors import BusinessException, ErrorCode
from app.domains.kopis.sync_service import KopisSyncService
from app.domains.tour.state_service import last_success_at, record_success

STATE_ID = 2
SYNC_INTERVAL = timedelta(hours=24)
RETRY_INTERVAL = timedelta(hours=6)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class KopisSyncScheduler:
    """수집 루프를 daemon 스레드로 실행한다. 프로세스당 한 번만 시작된다."""

    def __init__(self):
        self._start_lock = Lock()
        self._started = False
        self._stop = Event()

    def start(self, app):
        """수집 스레드를 시작한다. 이미 시작했거나 키가 없으면 아무것도 하지 않는다."""
        with self._start_lock:
            if self._started:
                return
            if not app.config.get("KOPIS_API_KEY"):
                app.logger.info("KOPIS_API_KEY가 없어 공연 수집을 시작하지 않습니다.")
                return
            Thread(target=self._run_loop, args=(app,), daemon=True, name="kopis-sync").start()
            self._started = True

    def run_once(self, app):
        """수집할 때가 됐으면 한 번 수집한다. 다음 판단까지 기다릴 초를 반환한다."""
        with app.app_context():
            completed_at = last_success_at(STATE_ID)
            due_at = completed_at + SYNC_INTERVAL if completed_at else None
            now = _utcnow()
            if due_at and due_at > now:
                return (due_at - now).total_seconds()
            report = KopisSyncService().sync_performances()
            if report["complete"]:
                record_success(STATE_ID)
                app.logger.info(
                    "공연 자동 갱신 완료: 신규 %s건, 갱신 %s건, 제외 %s건, TourAPI 중복 %s건",
                    report["saved"], report["updated"], report["skipped"], len(report["duplicates"]),
                )
                return SYNC_INTERVAL.total_seconds()
            error = ErrorCode.KOPIS_SYNC_INCOMPLETE
            app.logger.error("%s: %s / 결과: %s", error.code, error.message, report)
            return RETRY_INTERVAL.total_seconds()

    def _run_loop(self, app):
        while not self._stop.is_set():
            try:
                wait_seconds = self.run_once(app)
            except BusinessException as error:
                wait_seconds = RETRY_INTERVAL.total_seconds()
                app.logger.error("%s: %s / 상세: %s", error.error_code.code, error.message, error.extra)
            except Exception:
                # 예외가 스레드 밖으로 나가면 스케줄이 영구 중단되므로 모두 잡아 로그만 남긴다.
                wait_seconds = RETRY_INTERVAL.total_seconds()
                app.logger.exception("공연 정기 갱신 중 오류")
            # 앱 컨텍스트 밖에서 대기해 DB 연결을 점유하지 않는다.
            self._stop.wait(wait_seconds)


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
kopis_sync_scheduler = KopisSyncScheduler()
