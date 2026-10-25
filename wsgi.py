import os

from app import create_app

# Flask CLI와 WSGI 진입점은 이 app 객체를 import한다. 객체 생성만으로
# 예약 작업을 시작하지 않아 DB 마이그레이션 명령이 수집을 실행하지 않는다.
app = create_app()

if __name__ == '__main__':
    # README의 python wsgi.py 실행 경로에서만 예약 작업을 등록한다.
    # Flask debug 재시작 기능은 감시용 부모와 요청 처리용 자식을 각각
    # 실행한다. WERKZEUG_RUN_MAIN이 true인 자식에서만 시작해야 두 번
    # 수집하지 않는다. 수동 실행 파일은 이 경로를 거치지 않는다.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from app.domains.tour.scheduler import festival_sync_scheduler

        festival_sync_scheduler.start(app)
    # 예약 작업은 daemon 스레드라 서버 시작을 기다리게 하지 않는다.
    # 서버가 다시 켜지면 DB 성공 시각을 읽고 남은 12시간만 기다린다.
    app.run(debug=True)
