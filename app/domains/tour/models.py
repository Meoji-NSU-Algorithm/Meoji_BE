"""전국 축제 전체 수집의 마지막 성공 시각을 저장하는 ORM 모델.

events.updated_at은 축제 한 건의 수정 시각이다. 목록의 마지막 페이지까지
조회했는지, 모든 상세 데이터가 저장됐는지를 이 값으로 판단할 수 없으므로
전체 작업의 완료 시각을 별도 테이블 한 행에 저장한다.
"""

from app.core.extensions import db


class TourSyncState(db.Model):
    # 현재 예약 작업은 전국 축제 한 종류다. ID 1은 행사를 식별하는
    # events.id와 무관하며, 이 작업의 상태 행 하나를 찾기 위한 고정 키다.
    # 이 상태를 사용하는 모든 수집 실행이 같은 행을 읽고 갱신한다.
    __tablename__ = "tour_sync_state"

    id = db.Column(db.Integer, primary_key=True)
    # NULL은 마이그레이션 뒤 아직 전체 성공 기록이 없다는 뜻이다.
    # 이 경우 예약 작업은 서버 시작 시 바로 수집한다. 완전 성공하면
    # record_success()가 UTC 완료 시각으로 바꾼다. MySQL DATETIME은
    # 시간대를 저장하지 않으므로 값 자체를 UTC로 해석하는 약속이 필요하다.
    last_success_at = db.Column(db.DateTime, nullable=True)
