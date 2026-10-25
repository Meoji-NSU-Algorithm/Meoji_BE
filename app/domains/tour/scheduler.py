"""웹서버가 켜져 있는 동안 전국 축제 수집을 예약한다.

실행 흐름:
1. 서버가 시작되면 DB의 마지막 *전체 성공* 시각을 읽는다.
2. 그 시각에서 12시간이 지나지 않았으면 남은 시간만 기다린다.
3. 시간이 지났으면 TourAPI 목록과 상세를 수집하고 DB에 추가·갱신한다.
4. 모든 항목을 처리한 경우에만 성공 시각을 DB에 기록한다.

성공 시각은 DB에 남으므로 서버가 재시작되어도 12시간 주기가 유지된다.
실패 뒤의 다음 시도 시각은 이 프로세스의 메모리에만 둔다. 실패는 성공으로
간주하지 않고, 서버 재시작 후에는 다시 시도할 수 있게 하기 위해서다.
현재 실행 경로는 README의 ``python wsgi.py`` 단일 서버 실행이다.
"""

from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread

from app.core.errors import BusinessException, ErrorCode
from app.domains.tour.sync_service import TourSyncService
from app.domains.tour.state_service import last_success_at, record_success


# 성공 시각과 다음 실행 시각은 UTC로 계산한다. 로그·DB에도 같은 기준을 사용한다.
SYNC_INTERVAL_SECONDS = 12 * 60 * 60
SYNC_INTERVAL = timedelta(seconds=SYNC_INTERVAL_SECONDS)


class FestivalSyncScheduler:
    """자동 수집 루프를 서버 프로세스당 하나만 실행한다.

    이 잠금은 한 프로세스 안의 중복 시작만 막는다. 서버 워커를 여러 개로 늘리면
    각 워커가 독립 프로세스이므로 별도 공용 잠금 방식이 필요하다.
    """

    def __init__(self):
        # start()가 동시에 호출돼도 스레드가 두 개 생기지 않도록 보호한다.
        # _stop은 대기 중단에 쓰는 이벤트다. sleep 대신 Event.wait()를 써서
        # 테스트에서 실제 12시간을 기다리지 않고도 예약 흐름을 확인할 수 있다.
        # daemon 스레드는 웹서버 프로세스가 끝날 때 함께 종료된다.
        self._start_lock = Lock()
        self._started = False
        self._stop = Event()

    def start(self, app):
        """Flask 요청 처리와 분리된 예약 스레드를 한 번만 시작한다.

        app은 wsgi.py가 만든 Flask 객체다. 이 함수는 DB를 조회하지 않는다.
        DB 조회는 스레드 안에서 앱 컨텍스트를 연 뒤 수행한다.
        """
        with self._start_lock:
            if self._started:
                return
            # 전국 수집은 수백 건의 상세 API를 호출해 오래 걸릴 수 있다.
            # daemon 스레드로 실행해 웹서버 시작과 HTTP 요청 처리를 막지 않는다.
            thread = Thread(target=self._run_loop, args=(app,), daemon=True, name="festival-sync")
            thread.start()
            self._started = True

    def _run_loop(self, app):
        """DB의 마지막 성공 시각을 매 차례 읽고 수집 또는 대기한다.

        성공 시각이 비어 있으면 바로 수집하고, 값이 있다면 12시간이 지난
        뒤에 수집한다. 반환값은 없으며 오류는 로그에 남기고 다음 시도를 예약한다.
        """
        # 성공 시각은 DB에 영구 저장한다. retry_at은 이번 서버 실행 중 실패한
        # 뒤에만 설정한다. 예: 09시에 성공하고 21시 재수집이 실패했다면
        # DB에는 09시가 남지만, 이 스레드는 다음날 09시까지 재시도를 늦춘다.
        # 프로세스를 재시작하면 retry_at은 사라지고 DB 성공 시각만 사용한다.
        retry_at = None
        while not self._stop.is_set():
            # DB 접속 실패 시에는 성공 시각을 조회할 수도 없다. 이 검사 없이
            # 바로 while 처음으로 돌아가면 DB 오류 로그가 계속 쌓인다.
            # retry_at이 남아 있는 동안에는 DB 접근 전에 Event.wait()로 쉰다.
            # DB의 DATETIME은 시간대 정보가 없는 UTC 값이다. 같은 형식으로
            # 현재 시각을 만들어 마지막 성공·재시도 시각과 비교한다.
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if retry_at and retry_at > now:
                self._stop.wait((retry_at - now).total_seconds())
                continue
            try:
                wait_seconds = None
                # TourSyncService와 상태 저장 함수는 db.engine을 사용한다.
                # HTTP 요청 밖의 스레드이므로 Flask 앱 컨텍스트를 직접 열고,
                # 수집 또는 DB 조회가 끝나면 닫는다. 긴 대기 중에는 유지하지 않는다.
                with app.app_context():
                    completed_at = last_success_at()
                    # 예: 2026-10-02 09:00 UTC가 마지막 성공 시각이면 다음
                    # 실행 시각은 같은 날 21:00 UTC다. DB와 현재 시각을 모두
                    # UTC로 취급하므로 서버 OS의 현지 시간 설정과 무관하다.
                    # 신규 DB의 NULL 상태처럼 성공 기록이 없으면 즉시 수집한다.
                    # 기록이 있으면 서버 재시작 시각이 아니라 성공 시각에
                    # 12시간을 더한다. 예: 09시 성공 후 15시에 재시작하면
                    # 6시간만 기다리고 21시에 수집한다.
                    due_at = completed_at + SYNC_INTERVAL if completed_at else None
                    # 최근 실패가 있었다면 성공 기준 시각과 실패 후 재시도
                    # 시각 중 늦은 쪽을 택해 같은 작업을 연속 호출하지 않는다.
                    if retry_at and (due_at is None or retry_at > due_at):
                        due_at = retry_at
                    now = datetime.now(timezone.utc).replace(tzinfo=None)
                    if due_at and due_at > now:
                        # 아직 실행 시각 전이면 필요한 초만 기다린다. 대기 중
                        # 수동 파일이 성공해 기준 시각이 바뀔 수 있다. 따라서
                        # 대기가 끝났다고 바로 수집하지 않고 DB를 다시 읽는다.
                        # Event.wait()는 초 단위가 필요하다. 대기 자체는 아래
                        # 앱 컨텍스트 밖에서 해 DB 연결을 오래 점유하지 않는다.
                        wait_seconds = (due_at - now).total_seconds()
                    else:
                        # sync_festivals()는 각 축제를 독립 트랜잭션으로 저장한다.
                        # 한 건 실패해도 다음 건을 처리하고 report.failures에 남기므로
                        # 예외가 없다는 이유만으로 전체 성공이라고 판단할 수 없다.
                        # 인자를 생략하면 한국 시간의 7일 전부터 전국 행사와
                        # 각 항목의 상세를 다시 가져온다. 지난 행사도 DB에 보관하고
                        # 목록 API에서만 종료일을 기준으로 숨긴다.
                        report = TourSyncService().sync_festivals()
                        if report["complete"]:
                            # complete=True는 건별·목록 페이지 실패가 모두 없다는 뜻이다.
                            # 이때만 성공 시각을 기록한다. 기록 작업까지 실패하면
                            # 아래 예외 처리로 넘어가 다음 주기에 전체 재수집한다.
                            record_success()
                            retry_at = None
                            app.logger.info("축제 자동 갱신 완료: 저장 %s건", report["saved"])
                        else:
                            # 앞서 저장한 축제 행은 유지된다. 전체 성공 시각은
                            # 그대로 두고 12시간 뒤 동일 범위를 다시 확인한다.
                            retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                            error = ErrorCode.TOUR_SYNC_INCOMPLETE
                            app.logger.error("%s: %s / 결과: %s", error.code, error.message, report)
                if wait_seconds is not None:
                    # DB 세션과 앱 컨텍스트를 닫은 상태에서 기다린다. 대기 동안
                    # DB 연결을 붙잡거나 웹 요청에서 쓸 연결을 점유하지 않는다.
                    app.logger.info("축제 자동 갱신 대기: 다음 시각 %s UTC", due_at)
                    self._stop.wait(wait_seconds)
            except BusinessException as error:
                # 수집 서비스가 분류한 API·데이터 오류는 원래 ErrorCode로
                # 기록한다. 성공 시각은 건드리지 않고 다음 재시도만 예약한다.
                # 항목별 실패는 sync_festivals()가 report에 모으므로 이
                # 분기는 초기화·상태 처리 중 던져진 오류를 주로 받는다.
                retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                app.logger.error("%s: %s / 상세: %s", error.error_code.code, error.message, error.extra)
            except Exception:
                # DB 연결 실패·코드 오류처럼 분류되지 않은 예외는 공통 예약
                # 오류 코드와 traceback을 남긴다. 예외를 스레드 밖으로 보내면
                # 이후 예약이 영구 중단되므로, 여기서 잡고 다음 주기를 유지한다.
                retry_at = datetime.now(timezone.utc).replace(tzinfo=None) + SYNC_INTERVAL
                error = ErrorCode.TOUR_SYNC_SCHEDULE_FAILED
                app.logger.exception("%s: %s", error.code, error.message)


# wsgi.py가 이 인스턴스를 가져다 쓴다. 수동 수집 파일은 이를 참조하지 않는다.
festival_sync_scheduler = FestivalSyncScheduler()
