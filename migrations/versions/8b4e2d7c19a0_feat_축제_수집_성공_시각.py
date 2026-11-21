"""feat: 전국 축제 전체 수집의 마지막 성공 시각 저장

Revision ID: 8b4e2d7c19a0
Revises: 62d4e8a91b03

기존 events 데이터는 변경하지 않는다. 기존 DB에 행사 행이 있어도 이
마이그레이션만으로 전체 수집 성공을 증명할 수 없어서 새 상태는 NULL로 둔다.
"""

from alembic import op
import sqlalchemy as sa


revision = "8b4e2d7c19a0"
down_revision = "62d4e8a91b03"
branch_labels = None
depends_on = None


def upgrade():
    # events.updated_at은 행사 한 건의 수정 시각일 뿐, 전체 페이지와
    # 상세 조회가 모두 성공했는지는 알려주지 않는다. 예약 여부만 판단하는
    # 단일 행을 따로 만든다. 이 테이블은 앱의 TourSyncState 모델과
    # 같은 이름·타입·NULL 허용 여부를 가져야 Alembic 검사에서
    # 불필요한 스키마 변경으로 인식되지 않는다.
    table = op.create_table(
        "tour_sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
    )
    # ID 1은 전국 축제 수집 작업을 뜻하며 events.id와 관련이 없다.
    # NULL이면 성공 기록이 없으므로
    # 첫 서버 실행에서 수집하고, 완전 성공한 뒤 record_success()가 채운다.
    # 기존 events 행의 수나 MAX(updated_at)을 성공 시각으로 사용하지 않는다.
    op.bulk_insert(table, [{"id": 1, "last_success_at": None}])


def downgrade():
    # 이 테이블은 예약 상태만 보관하며 행사 데이터와 FK로 연결되지 않는다.
    # 롤백 시 행사 데이터는 유지하고 성공 시각 기록만 제거한다.
    # 다시 upgrade하면 NULL에서 시작하므로 최초 실행 때 재수집한다.
    op.drop_table("tour_sync_state")
