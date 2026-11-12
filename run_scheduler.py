"""축제 수집 스케줄러만 실행하는 전용 프로세스의 진입점."""
import logging
import signal

from app import create_app
from app.domains.tour.scheduler import festival_sync_scheduler


def main():
    # 수집 로그가 터미널과 docker logs에 나오도록 INFO 이상을 출력한다.
    logging.basicConfig(level=logging.INFO)
    app = create_app()

    def handle_stop(signum, frame):
        festival_sync_scheduler.stop()

    # SIGTERM은 docker stop, SIGINT는 Ctrl+C가 보내는 신호다.
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    festival_sync_scheduler.run_forever(app)


if __name__ == "__main__":
    main()
