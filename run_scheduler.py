"""수집 스케줄러 전용 프로세스 진입점. 축제(TourAPI)·공연(KOPIS) 수집을 한 프로세스에서 시작한다.

웹 서버(gunicorn 등)는 wsgi.py의 app만 쓰고 스케줄러를 시작하지 않는다. 배포할 때는 이 파일을
컨테이너 하나로 띄운다. 같은 스케줄러를 2개 이상 띄우면 수집이 중복되므로 복제하지 않는다.
"""
from threading import Event

from app import create_app
from app.domains.kopis.scheduler import kopis_sync_scheduler
from app.domains.tour.scheduler import festival_sync_scheduler

app = create_app()

festival_sync_scheduler.start(app)
kopis_sync_scheduler.start(app)

# 스케줄러 스레드는 daemon이라 메인 프로세스가 끝나면 같이 종료된다. 계속 대기해 살려 둔다.
Event().wait()
