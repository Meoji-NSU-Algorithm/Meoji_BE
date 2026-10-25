"""전체 축제 수집의 마지막 성공 시각을 DB에서 읽고 저장한다.

``TourSyncService.sync_festivals()``는 항목별로 저장하고 성공 여부를 report로
반환한다. ``record_success()``는 그 report가 완전히 성공한 *뒤에만*
호출되어야 한다. 상태 저장 로직을 예약 루프와 분리해 DB 세션의 시작·종료를
이 파일에서 관리한다. 수동 실행 프로그램을 별도로 두더라도 같은 함수를
가져다 쓸 수 있으며, 이 모듈은 수동 프로그램에 의존하지 않는다.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.extensions import db
from app.domains.tour.models import TourSyncState


def last_success_at():
    """마지막 전체 성공 시각(UTC)을 반환한다. 기록이 없으면 None이다.

    호출 전에 Flask 앱 컨텍스트가 있어야 한다. 반환값은 시간대 정보가 없는
    datetime이지만 값 자체는 UTC다. 예약 작업도 현재 UTC 시각에서
    tzinfo를 제거해 같은 형식으로 만든 뒤 비교한다.
    """
    # 예: DB에 2026-10-02 09:00:00이 있으면 반환값도 같은 UTC 시각이다.
    # 예약 루프는 여기에 12시간을 더해 다음 실행 시각을 계산한다.
    # ORM 객체를 세션 밖으로 넘기지 않고 시각 값만 꺼낸다. 예약 루프가
    # 12시간 대기할 때 DB 연결이나 트랜잭션을 계속 붙잡지 않기 위해서다.
    with Session(db.engine) as session:
        # 마이그레이션이 ID 1 행을 만들지만, 행이 누락돼도 첫 수집을
        # 진행할 수 있도록 None을 그대로 반환한다.
        state = session.get(TourSyncState, 1)
        return state.last_success_at if state else None


def record_success():
    """전체 수집 성공 뒤에만 호출해 완료 시각을 UTC로 기록한다.

    이 함수의 DB 트랜잭션은 행사별 저장 트랜잭션과 별개다. 시각 저장에
    실패하면 호출자도 실패로 처리하므로 다음 예약 시 다시 수집할 수 있다.
    """
    # 이 함수는 report["complete"]를 검사하지 않는다. 호출하는 쪽이
    # 전체 성공을 확인한 후에만 호출해야 상태값이 실제 결과와 일치한다.
    # MySQL DATETIME은 시간대를 저장하지 않는다. 서버 OS의 현지 시간이
    # 달라져도 계산 결과가 같도록 UTC로 바꾼 뒤 tzinfo 없이 저장한다.
    completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db.engine) as session, session.begin():
        # 수집 방식과 관계없이 같은 ID 1 행을 사용한다. 기존 행을 잠그면
        # 거의 동시에 기록하려 할 때 한쪽이 다른 쪽의 갱신을 기다린다.
        # 마이그레이션이 행을 생성하지만 누락됐다면 새로 만든다.
        # with 블록이 정상 종료될 때만 COMMIT되고 예외 시 ROLLBACK된다.
        state = session.get(TourSyncState, 1, with_for_update=True)
        if state is None:
            state = TourSyncState(id=1, last_success_at=completed_at)
            session.add(state)
        else:
            state.last_success_at = completed_at
    # 호출자가 저장된 기준 시각을 로그 등에 사용할 수 있게 반환한다.
    return completed_at
