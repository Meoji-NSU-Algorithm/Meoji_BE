"""웹서버 프로세스 안에서 1시간 주기로 리뷰에 붙지 않은 업로드 이미지를 정리하는 스케줄러.

정리를 업로드 요청 밖에서 돌려, 저장소가 느려도 사용자의 업로드 응답이 늦어지지 않게 한다.
한 번에 service._CLEANUP_BATCH개까지만 지우므로, 다 지우지 못한 업로드는 다음 주기에 이어서 정리된다.
"""

from threading import Event, Lock, Thread

from app.domains.reviews.service import cleanup_unattached_uploads


CLEANUP_INTERVAL_SECONDS = 60 * 60


class UploadCleanupScheduler:
    """정리 루프를 daemon 스레드로 실행한다. 프로세스당 한 번만 시작된다.

    tour.scheduler.FestivalSyncScheduler와 같은 구조다. 워커를 여러 개 띄우면 워커마다 실행되지만,
    cleanup_unattached_uploads가 대상 행을 잠그므로 같은 업로드를 두 번 처리하지 않는다.
    """

    def __init__(self):
        # sleep 대신 _stop.wait()로 대기하므로 set()하면 대기를 즉시 깨울 수 있다.
        self._start_lock = Lock()
        self._started = False
        self._stop = Event()

    def start(self, app):
        """정리 스레드를 시작한다. 이미 시작됐으면 아무것도 하지 않는다.

        Args:
            app: 스레드에서 앱 컨텍스트를 열 때 쓰는 Flask 앱.
        """
        with self._start_lock:
            if self._started:
                return
            thread = Thread(target=self._run_loop, args=(app,), daemon=True, name="review-upload-cleanup")
            thread.start()
            self._started = True

    def _run_loop(self, app):
        """정리를 한 번 실행하고 다음 주기까지 대기한다. 오류가 나도 루프는 종료되지 않는다."""
        while not self._stop.is_set():
            try:
                # 요청 밖 스레드라 앱 컨텍스트를 직접 열고, 대기 전에 닫아 DB 연결을 점유하지 않는다.
                with app.app_context():
                    deleted = cleanup_unattached_uploads()
                    if deleted:
                        app.logger.info("미첨부 리뷰 이미지 정리: %d개 삭제", deleted)
            except Exception:
                # 예외가 스레드 밖으로 나가면 정리가 영구 중단되므로 모두 잡아 로그만 남긴다.
                app.logger.exception("미첨부 리뷰 이미지 정리 스케줄 실패")
            self._stop.wait(CLEANUP_INTERVAL_SECONDS)


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
upload_cleanup_scheduler = UploadCleanupScheduler()
