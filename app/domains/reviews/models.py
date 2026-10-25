# 리뷰 모델과 공통 시간 필드를 정의한다.

from datetime import datetime, timezone

from app.core.extensions import db


# 모델의 생성 및 수정 시각을 공통으로 관리한다.
class TimestampMixin:
    # 레코드 생성 시 현재 UTC 시각을 저장한다.
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # 레코드 생성 시 저장하고 수정 시 현재 UTC 시각으로 갱신한다.
    updated_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# 행사에 작성된 리뷰 정보를 저장한다.
class Review(TimestampMixin, db.Model):
    __tablename__ = "review"

    # 리뷰의 고유 ID
    id = db.Column(db.Integer, primary_key=True)

    # 리뷰를 작성한 사용자의 ID를 User 테이블과 연결한다.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    # 리뷰가 작성된 행사의 ID를 Event 테이블과 연결한다.
    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)

    # 리뷰와 행사 간의 관계를 설정한다.
    event = db.relationship("Event")

    # 0.5 단위의 평점을 저장한다.
    rating = db.Column(db.Numeric(2, 1), nullable=False)

    # 리뷰 내용을 저장한다.
    content = db.Column(db.Text, nullable=False)

    # DB에서도 평점 범위와 0.5 단위 입력을 검증한다.
    __table_args__ = (
        db.CheckConstraint("rating >= 0.5 AND rating <= 5 AND rating * 2 = FLOOR(rating * 2)", name="ck_review_rating"),
    )