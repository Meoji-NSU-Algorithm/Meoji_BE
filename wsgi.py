"""WSGI/Flask CLI 진입점. 앱 객체를 만들고, 직접 실행할 때만 축제 갱신 스케줄러를 시작한다."""
import os

from app import create_app

# 객체 생성만으로는 스케줄러가 시작되지 않는다. flask db 같은 CLI 명령이 수집을 실행하지 않게 하기 위해서다.
app = create_app()

if __name__ == '__main__':
    # 디버그 모드의 자동 재시작은 감시용 부모와 요청 처리용 자식 프로세스를 따로 띄운다.
    # 수집이 중복 실행되지 않도록 디버그일 때는 WERKZEUG_RUN_MAIN이 true인 자식에서만 시작한다.
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    if not debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from app.domains.tour.scheduler import festival_sync_scheduler

        festival_sync_scheduler.start(app)
    # 스케줄러는 daemon 스레드라 서버 시작을 막지 않는다.
    # 재시작 후에는 DB에 기록된 마지막 성공 시각을 읽어 남은 시간만 기다린다.
    app.run(debug=debug)
