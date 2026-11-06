"""웹서버 프로세스 안에서 1시간 주기로 리뷰에 붙지 않은 업로드 이미지를 정리하는 스케줄러.

정리를 업로드 요청 밖에서 돌려, 저장소가 느려도 사용자의 업로드 응답이 늦어지지 않게 한다.
한 주기에 service._CLEANUP_BATCH개씩 최대 MAX_BATCHES_PER_RUN번 지우고, 남은 업로드는 다음 주기에 이어서 정리한다.
"""

from threading import Event, Lock, Thread

from app.domains.reviews.service import cleanup_unattached_uploads


CLEANUP_INTERVAL_SECONDS = 60 * 60

# 한 주기에 반복하는 최대 배치 수. 배치당 _CLEANUP_BATCH(50)개라 한 주기에 최대 1000개를 지운다.
MAX_BATCHES_PER_RUN = 20


def run_cleanup_until_empty() -> int:
    """정리 대상이 남아 있으면 배치를 반복해 지운 파일 수의 합을 반환한다.

    한 배치에서 지운 파일이 없으면(대상 없음, 저장소 실패, 리뷰에 붙은 key뿐) 멈춘다.
    저장소가 계속 실패할 때 같은 key를 붙잡고 반복하지 않게 하고, 남은 것은 다음 주기에 이어서 처리한다.
    """
    total = 0
    for _ in range(MAX_BATCHES_PER_RUN):
        deleted = cleanup_unattached_uploads()
        if not deleted:
            break
        total += deleted
    return total


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
                    deleted = run_cleanup_until_empty()
                    if deleted:
                        app.logger.info("미첨부 리뷰 이미지 정리: %d개 삭제", deleted)
            except Exception:
                # 예외가 스레드 밖으로 나가면 정리가 영구 중단되므로 모두 잡아 로그만 남긴다.
                app.logger.exception("미첨부 리뷰 이미지 정리 스케줄 실패")
            self._stop.wait(CLEANUP_INTERVAL_SECONDS)


# wsgi.py가 시작하는 프로세스 단위 인스턴스.
upload_cleanup_scheduler = UploadCleanupScheduler()
