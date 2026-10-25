"""웹서버 프로세스 안에서 12시간 주기로 전국 축제 수집을 실행하는 스케줄러.

마지막 전체 성공 시각은 DB에 두어 재시작해도 주기가 유지된다. 실패 후 재시도 시각은
프로세스 메모리에만 두므로, 재시작하면 DB의 성공 시각 기준으로 다시 판단한다.
시각은 모두 UTC(tzinfo 없는 naive datetime)로 비교한다.
"""

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from app.core.errors import BusinessException, ErrorCode
from app.domains.tour.sync_service import TourSyncService
from app.domains.tour.state_service import last_success_at, record_success


SYNC_INTERVAL_SECONDS = 12 * 60 * 60
SYNC_INTERVAL = timedelta(seconds=SYNC_INTERVAL_SECONDS)


class FestivalSyncScheduler:
    """수집 루프를 daemon 스레드로 실행한다. 프로세스당 한 번만 시작된다.

    중복 시작 방지는 프로세스 내부 잠금뿐이다. 워커를 여러 개 띄우면 워커마다
    실행되므로 별도의 공용 잠금이 필요하다.
    """

    def __init__(self):
        # sleep 대신 _stop.wait()로 대기하므로 set()하면 대기를 즉시 깨울 수 있다.
        self._start_lock = Lock()
        self._started = False
        self._stop = Event()

    def start(self, app):
        """수집 스레드를 시작한다. 이미 시작됐으면 아무것도 하지 않는다.

        Args:
            app: 스레드에서 앱 컨텍스트를 열 때 쓰는 Flask 앱.
        """
        with self._start_lock:
            if self._started:
                return
            # 수집은 오래 걸리므로 서버 시작과 요청 처리를 막지 않도록 daemon 스레드로 돌린다.
            thread = Thread(target=self._run_loop, args=(app,), daemon=True, name="festival-sync")
            thread.start()
            self._started = True

    def _run_loop(self, app):
        """마지막 성공 시각을 매번 DB에서 읽어 수집하거나 다음 시각까지 대기한다.

        성공 기록이 없으면 즉시 수집하고, 있으면 성공 시각 + 12시간에 수집한다.
        오류는 로그로 남기고 12시간 뒤 재시도하며 루프는 종료되지 않는다.
        """
        # retry_at은 실패 후 재시도 시각으로, 메모리에만 있다. 예: 09시 성공 뒤
        # 21시 수집이 실패하면 DB는 09시 그대로지만 다음 시도는 다음 날 09시다.
        retry_at = None
        while not self._stop.is_set():
            # 재시도 대기 중에는 DB에 접근하지 않는다. DB 장애로 실패했을 때
            # 즉시 재조회를 반복하며 오류 로그가 쌓이는 것을 막는다.
            # DB 값과 같은 형식(UTC naive)으로 현재 시각을 만들어 비교한다.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if retry_at and retry_at > now:
                self._stop.wait((retry_at - now).total_seconds())
                continue
            try:
                wait_seconds = None
                # 요청 밖 스레드라 앱 컨텍스트를 직접 열고, 긴 대기 전에 닫는다.
                with app.app_context():
                    completed_at = last_success_at()
                    # 다음 실행 시각은 서버 시작 시각이 아니라 마지막 성공 시각 + 12시간이다.
                    # 예: 09시 성공 후 15시에 재시작하면 21시까지 6시간만 기다린다.
                    # 성공 기록이 없으면(None) 즉시 수집한다.
                    due_at = completed_at + SYNC_INTERVAL if completed_at else None
                    # 최근 실패가 있으면 성공 기준 시각과 재시도 시각 중 늦은 쪽을 따른다.
                    if retry_at and (due_at is None or retry_at > due_at):
                        due_at = retry_at
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    if due_at and due_at > now:
                        # 대기 중 성공 시각이 바뀔 수 있으므로, 대기 후 바로 수집하지 않고
                        # 루프 처음에서 DB를 다시 읽어 판단한다.
                        wait_seconds = (due_at - now).total_seconds()
                    else:
                        # 건별 실패는 예외 없이 report["failures"]에 쌓이므로
                        # 예외가 없다는 것만으로 성공이라 볼 수 없다.
                        report = TourSyncService().sync_festivals()
                        if report["complete"]:
                            # complete는 건별·목록 페이지 실패가 하나도 없다는 뜻이다.
                            # 기록이 실패하면 아래 except로 넘어가 12시간 뒤 다시 수집한다.
                            record_success()
                            retry_at = None
                            app.logger.info("축제 자동 갱신 완료: 저장 %s건", report["saved"])
                        else:
                            # 이미 저장된 행은 유지하고 성공 시각은 갱신하지 않는다.
                            retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                            error = ErrorCode.TOUR_SYNC_INCOMPLETE
                            app.logger.error("%s: %s / 결과: %s", error.code, error.message, report)
                if wait_seconds is not None:
                    # 앱 컨텍스트 밖에서 대기해 DB 연결을 점유하지 않는다.
                    app.logger.info("축제 자동 갱신 대기: 다음 시각 %s UTC", due_at)
                    self._stop.wait(wait_seconds)
            except BusinessException as error:
                # 건별·목록 조회 실패는 sync_festivals()가 report에 모으므로
                # 여기에는 그 밖의 위치에서 올라온 분류된 오류가 온다.
                retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                app.logger.error("%s: %s / 상세: %s", error.error_code.code, error.message, error.extra)
            except Exception:
                # 예외가 스레드 밖으로 나가면 스케줄이 영구 중단되므로 모두 잡아 로그만 남긴다.
                retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                error = ErrorCode.TOUR_SYNC_SCHEDULE_FAILED
                app.logger.exception("%s: %s", error.code, error.message)


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
festival_sync_scheduler = FestivalSyncScheduler()
