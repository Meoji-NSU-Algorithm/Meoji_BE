"""전체 축제 수집의 마지막 성공 시각을 DB에서 읽고 기록한다.

`TourSyncService.sync_festivals()`는 건별로 저장하고 결과를 report로 반환한다.
`record_success()`는 report의 `complete`가 True일 때만 호출해야 한다.
세션 관리를 이 모듈에 모아 스케줄러가 DB 연결을 붙잡지 않게 한다.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.extensions import db
from app.domains.tour.models import TourSyncState


def last_success_at() -> datetime | None:
    """마지막 전체 성공 시각을 반환한다. 기록이 없으면 None이다.

    Flask 앱 컨텍스트가 필요하다. 반환값은 tzinfo 없는 naive datetime이지만 값은 UTC다.
    """
    # ORM 객체 대신 시각 값만 꺼내 세션을 바로 닫는다. 긴 대기 중 DB 연결을 잡지 않기 위해서다.
    with Session(db.engine) as session:
        # 행이 없어도(마이그레이션 누락) 첫 수집이 진행되도록 None을 반환한다.
        state = session.get(TourSyncState, 1)
        return state.last_success_at if state else None


def record_success() -> datetime:
    """전체 수집 성공 시각을 UTC로 기록하고 그 값을 반환한다.

    report["complete"]는 검사하지 않으므로 호출자가 전체 성공을 확인해야 한다.
    저장에 실패하면 예외가 전파되어 다음 주기에 전체를 다시 수집한다.
    """
    # 서버 OS의 시간대와 무관하게 UTC로 맞춰 tzinfo 없이 저장한다.
    completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(db.engine) as session, session.begin():
        # 동시에 기록하려는 경우 행 잠금으로 순서를 맞춘다. 행이 없으면 새로 만든다.
        state = session.get(TourSyncState, 1, with_for_update=True)
        if state is None:
            state = TourSyncState(id=1, last_success_at=completed_at)
            session.add(state)
        else:
            state.last_success_at = completed_at
    return completed_at
