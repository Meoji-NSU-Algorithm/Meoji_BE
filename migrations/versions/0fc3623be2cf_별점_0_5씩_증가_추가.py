"""별점 0.5씩 증가 추가

Revision ID: 0fc3623be2cf
Revises: 12514c462a23
Create Date: 2026-10-03 01:34:03.094145

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision = '0fc3623be2cf'
down_revision = '12514c462a23'
branch_labels = None
depends_on = None


def upgrade():
    # ========================================================
    # Review 평점 자료형 변경
    # ========================================================
    #
    # 기존 rating은 SmallInteger 타입이었다.
    #
    # SmallInteger는 정수만 저장할 수 있기 때문에
    # 4.5, 3.5와 같은 0.5 단위의 평점을 저장할 수 없다.
    #
    # 따라서 Numeric(2, 1)로 변경한다.
    #
    # Numeric(2, 1)
    #   - 전체 자릿수: 최대 2자리
    #   - 소수점 이하: 1자리
    #
    # 예:
    #   0.5
    #   1.0
    #   2.5
    #   4.5
    #   5.0
    #
    # 기존 데이터는 정수이므로 Numeric(2, 1)으로
    # 변경해도 기존 값에는 문제가 없다.
    #
    with op.batch_alter_table('review', schema=None) as batch_op:

        # 기존 rating 컬럼을 SMALLINT에서
        # NUMERIC(2, 1)으로 변경한다.
        batch_op.alter_column(
            'rating',
            existing_type=mysql.SMALLINT(),
            type_=sa.Numeric(
                precision=2,
                scale=1
            ),
            existing_nullable=False
        )

        # ====================================================
        # 기존 평점 CheckConstraint 변경
        # ====================================================
        #
        # 기존 Constraint는
        #
        #   rating >= 1 AND rating <= 5
        #
        # 였기 때문에 0.5점이 허용되지 않는다.
        #
        # 따라서 기존 Constraint를 삭제하고
        # 0.5 ~ 5.0 범위 및 0.5 단위를 허용하는
        # 새로운 Constraint를 추가한다.
        #
        batch_op.drop_constraint(
            'ck_review_rating',
            type_='check'
        )

        batch_op.create_check_constraint(
            'ck_review_rating',
            'rating >= 0.5 '
            'AND rating <= 5 '
            'AND rating * 2 = FLOOR(rating * 2)'
        )


def downgrade():
    # ========================================================
    # Review 평점 자료형 원상 복구
    # ========================================================
    #
    # upgrade 이전의 SmallInteger 타입으로 되돌린다.
    #
    # 단, Numeric에 저장된 0.5 단위 값이 존재하는 상태에서
    # SmallInteger로 변경하면 데이터 손실 또는 변환 문제가
    # 발생할 수 있으므로 downgrade는 주의해서 사용해야 한다.
    #
    with op.batch_alter_table('review', schema=None) as batch_op:

        # 현재 0.5 단위 평점을 허용하는
        # CheckConstraint를 제거한다.
        batch_op.drop_constraint(
            'ck_review_rating',
            type_='check'
        )

        # 기존의 SmallInteger 타입으로 되돌린다.
        batch_op.alter_column(
            'rating',
            existing_type=sa.Numeric(
                precision=2,
                scale=1
            ),
            type_=mysql.SMALLINT(),
            existing_nullable=False
        )

        # 기존의 1~5점 제한을 다시 생성한다.
        batch_op.create_check_constraint(
            'ck_review_rating',
            'rating >= 1 AND rating <= 5'
        )