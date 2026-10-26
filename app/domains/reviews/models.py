"""리뷰 ORM 모델."""

from app.core.db import TimestampMixin
from app.core.extensions import db


class Review(TimestampMixin, db.Model):
    """행사에 사용자가 남긴 리뷰. created_at/updated_at은 TimestampMixin이 제공한다."""

    __tablename__ = "review"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)

    # 0.5 단위, 0.5~5.0
    rating = db.Column(db.Numeric(2, 1), nullable=False)

    content = db.Column(db.Text, nullable=False)

    # API 검증을 우회한 입력에도 평점 범위와 0.5 단위를 보장하고,
    # 한 사용자가 한 행사에 리뷰를 하나만 쓰도록 DB에서 강제한다.
    __table_args__ = (
        db.CheckConstraint("rating >= 0.5 AND rating <= 5 AND rating * 2 = FLOOR(rating * 2)", name="ck_review_rating"),
        db.UniqueConstraint("user_id", "event_id", name="uq_review_user_event"),
    )