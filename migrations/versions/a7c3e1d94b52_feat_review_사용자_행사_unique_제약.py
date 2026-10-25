"""feat: 사용자당 행사별 리뷰 1개 unique 제약

Revision ID: a7c3e1d94b52
Revises: fd8da9482b62
Create Date: 2026-10-25 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a7c3e1d94b52'
down_revision = 'fd8da9482b62'
branch_labels = None
depends_on = None


def upgrade():
    """(user_id, event_id) unique 제약을 추가한다.

    기존 데이터에 중복이 있으면 데이터를 지우지 않고 중단한다.
    """
    bind = op.get_bind()

    duplicates = bind.exec_driver_sql(
        "SELECT user_id, event_id, COUNT(*) AS c FROM review "
        "GROUP BY user_id, event_id HAVING c > 1 ORDER BY c DESC, user_id, event_id"
    ).fetchall()

    if duplicates:
        extra_rows = sum(row[2] - 1 for row in duplicates)
        sample = ", ".join(f"(user_id={row[0]}, event_id={row[1]}, {row[2]}건)" for row in duplicates[:10])
        raise RuntimeError(
            f"review 테이블에 같은 (user_id, event_id) 쌍이 중복된 데이터가 있어 unique 제약을 추가할 수 없다. "
            f"중복된 쌍은 {len(duplicates)}개이고, 초과 행은 총 {extra_rows}개이다. "
            f"데이터는 삭제하지 않았으므로 중복 리뷰를 직접 정리한 뒤 다시 업그레이드해야 한다. "
            f"중복 쌍(최대 10개): {sample}"
        )

    op.create_unique_constraint('uq_review_user_event', 'review', ['user_id', 'event_id'])


def downgrade():
    """unique 제약을 제거한다. user_id FK는 ix_review_user_id 인덱스가 받쳐 준다."""
    op.drop_constraint('uq_review_user_event', 'review', type_='unique')
