"""웹서버 프로세스 안에서 수집(축제·공연)을 주기적으로 실행하는 스케줄러.

SyncScheduler가 공통 동작을 맡고, 축제(FestivalSyncScheduler)와 공연(kopis.scheduler)은
주기·수집 함수·로그만 다르게 둔다. 마지막 전체 성공 시각은 DB(tour_sync_state)에 수집 종류별
행으로 두어 재시작해도 주기가 유지된다. 시각은 모두 UTC(tzinfo 없는 naive datetime)로 비교한다.
"""

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from app.core.errors import BusinessException, ErrorCode
from app.domains.tour.sync_service import TourSyncService
from app.domains.tour.state_service import last_success_at, record_success


SYNC_INTERVAL_SECONDS = 12 * 60 * 60
SYNC_INTERVAL = timedelta(seconds=SYNC_INTERVAL_SECONDS)


def _utcnow():
    """DB 값과 같은 형식(UTC naive)의 현재 시각."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SyncScheduler:
    """수집 루프를 daemon 스레드로 실행한다. 프로세스당 한 번만 시작된다.

    하위 클래스가 정하는 것: name, state_id, interval, retry_interval, config_key,
    incomplete_error, failed_error, sync(), log_success().

    중복 시작 방지는 프로세스 내부 잠금뿐이다. 워커를 여러 개 띄우면 워커마다
    실행되므로 별도의 공용 잠금이 필요하다.
    """

    name = ""  # 스레드 이름
    state_id = 1  # tour_sync_state의 행 번호(1: TourAPI 축제, 2: KOPIS 공연)
    interval = SYNC_INTERVAL  # 전체 성공 뒤 다음 수집까지의 간격
    retry_interval = SYNC_INTERVAL  # 실패 뒤 다시 시도하기까지의 간격
    config_key = None  # 있으면 이 설정값(API 키)이 비어 있을 때 시작하지 않는다
    incomplete_error = None  # 일부만 수집됐을 때 남길 ErrorCode
    failed_error = None  # 예상하지 못한 오류가 났을 때 남길 ErrorCode

    def __init__(self):
        # sleep 대신 _stop.wait()로 대기하므로 set()하면 대기를 즉시 깨울 수 있다.
        self._start_lock = Lock()
        self._started = False
        self._stop = Event()

    def sync(self):
        """수집을 실행하고 report(`complete` 키 포함)를 반환한다."""
        raise NotImplementedError

    def log_success(self, app, report):
        """전체 수집이 성공했을 때 남길 로그."""
        raise NotImplementedError

    def start(self, app):
        """수집 스레드를 시작한다. 이미 시작했거나 필요한 설정이 없으면 아무것도 하지 않는다.

        Args:
            app: 스레드에서 앱 컨텍스트를 열 때 쓰는 Flask 앱.
        """
        with self._start_lock:
            if self._started:
                return
            if self.config_key and not app.config.get(self.config_key):
                app.logger.info("%s가 없어 %s을 시작하지 않습니다.", self.config_key, self.name)
                return
            # 수집은 오래 걸리므로 서버 시작과 요청 처리를 막지 않도록 daemon 스레드로 돌린다.
            thread = Thread(target=self._run_loop, args=(app,), daemon=True, name=self.name)
            thread.start()
            self._started = True

    def run_once(self, app):
        """수집할 때가 됐으면 한 번 수집하고, 다음 판단까지 기다릴 초를 반환한다.

        다음 실행 시각은 서버 시작 시각이 아니라 마지막 성공 시각 + interval이다.
        예: 09시 성공 후 15시에 재시작하면 21시까지 6시간만 기다린다.
        성공 기록이 없으면(None) 즉시 수집한다.
        """
        # 요청 밖 스레드라 앱 컨텍스트를 직접 열고, 긴 대기 전에 닫는다.
        with app.app_context():
            completed_at = last_success_at(self.state_id)
            due_at = completed_at + self.interval if completed_at else None
            now = _utcnow()

            if due_at and due_at > now:
                # 대기 중 성공 시각이 바뀔 수 있으므로, 대기 후 바로 수집하지 않고
                # 호출자가 이 함수를 다시 불러 DB를 새로 읽어 판단한다.
                return (due_at - now).total_seconds()

            report = self.sync()

            # 건별 실패는 예외 없이 report["failures"]에 쌓이므로
            # 예외가 없다는 것만으로 성공이라 볼 수 없다.
            if report["complete"]:
                # complete는 건별·목록 페이지 실패가 하나도 없다는 뜻이다.
                # 기록이 실패하면 예외가 올라가 retry_interval 뒤 다시 수집한다.
                record_success(self.state_id)
                self.log_success(app, report)
                return self.interval.total_seconds()

            # 이미 저장된 행은 유지하고 성공 시각은 갱신하지 않는다.
            error = self.incomplete_error
            app.logger.error("%s: %s / 결과: %s", error.code, error.message, report)
            return self.retry_interval.total_seconds()

    def _run_loop(self, app):
        """run_once를 반복한다. 오류는 로그로 남기고 retry_interval 뒤 재시도하며 루프는 종료되지 않는다."""
        while not self._stop.is_set():
            try:
                wait_seconds = self.run_once(app)
            except BusinessException as error:
                # 건별·목록 조회 실패는 report에 모이므로 여기에는 그 밖의 위치에서 올라온 분류된 오류가 온다.
                wait_seconds = self.retry_interval.total_seconds()
                app.logger.error("%s: %s / 상세: %s", error.error_code.code, error.message, error.extra)
            except Exception:
                # 예외가 스레드 밖으로 나가면 스케줄이 영구 중단되므로 모두 잡아 로그만 남긴다.
                wait_seconds = self.retry_interval.total_seconds()
                error = self.failed_error
                app.logger.exception("%s: %s", error.code, error.message)

            # 앱 컨텍스트 밖에서 대기해 DB 연결을 점유하지 않는다.
            self._stop.wait(wait_seconds)


class FestivalSyncScheduler(SyncScheduler):
    """TourAPI 축제를 12시간 주기로 수집한다. 실패하면 12시간 뒤 다시 시도한다."""

    name = "festival-sync"
    incomplete_error = ErrorCode.TOUR_SYNC_INCOMPLETE
    failed_error = ErrorCode.TOUR_SYNC_SCHEDULE_FAILED

    def sync(self):
        return TourSyncService().sync_festivals()

    def log_success(self, app, report):
        app.logger.info("축제 자동 갱신 완료: 저장 %s건", report["saved"])


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
festival_sync_scheduler = FestivalSyncScheduler()
