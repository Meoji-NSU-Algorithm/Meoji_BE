"""전국 축제 전체 수집의 마지막 성공 시각을 저장하는 ORM 모델.

events.updated_at은 행사 한 건의 수정 시각이라 전체 수집이 끝났는지 알 수 없다.
그래서 전체 작업의 완료 시각을 별도 테이블의 한 행에 둔다.
"""

from app.core.extensions import db


class TourSyncState(db.Model):
    """수집 상태 단일 행. id=1 하나만 사용하며 events.id와는 무관하다."""

    __tablename__ = "tour_sync_state"

    id = db.Column(db.Integer, primary_key=True)
    # UTC 기준. DATETIME은 시간대를 저장하지 않으므로 값을 UTC로 해석하기로 한다.
    # NULL이면 전체 성공 기록이 없다는 뜻이고 스케줄러가 즉시 수집한다.
    last_success_at = db.Column(db.DateTime, nullable=True)
