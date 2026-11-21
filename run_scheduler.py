"""수집 스케줄러 전용 프로세스 진입점. 축제(TourAPI)·공연(KOPIS) 수집을 한 프로세스에서 시작한다.

웹 서버(gunicorn 등)는 wsgi.py의 app만 쓰고 스케줄러를 시작하지 않는다. 배포할 때는 이 파일을
컨테이너 하나로 띄운다. 같은 스케줄러를 2개 이상 띄우면 수집이 중복되므로 복제하지 않는다.
종료 신호(docker stop의 SIGTERM, Ctrl+C의 SIGINT)를 받으면 진행 중인 수집을 마친 뒤 종료한다.
"""
import logging
import signal

from app import create_app
from app.domains.kopis.scheduler import kopis_sync_scheduler
from app.domains.tour.scheduler import festival_sync_scheduler

SCHEDULERS = (festival_sync_scheduler, kopis_sync_scheduler)


def main():
    # 수집 로그(INFO)가 터미널과 docker logs에 나오도록 한다. 없으면 WARNING 이상만 나온다.
    logging.basicConfig(level=logging.INFO)
    app = create_app()

    def handle_stop(signum, frame):
        for scheduler in SCHEDULERS:
            scheduler.stop()

    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)

    for scheduler in SCHEDULERS:
        scheduler.start(app)
    # 스케줄러 스레드는 daemon이라 메인이 먼저 끝나면 수집 도중 끊긴다. 루프가 끝날 때까지 기다린다.
    for scheduler in SCHEDULERS:
        scheduler.join()


if __name__ == "__main__":
    main()
