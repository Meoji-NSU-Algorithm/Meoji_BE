"""리뷰 ORM 모델."""

from app.core.db import TimestampMixin
from app.core.extensions import db


class Review(TimestampMixin, db.Model):
    """행사에 사용자가 남긴 리뷰. created_at/updated_at은 TimestampMixin이 제공한다."""

    __tablename__ = "review"

    id = db.Column(db.Integer, primary_key=True)

    # 회원 탈퇴로 유저가 삭제되면 DB가 그 유저의 리뷰도 함께 삭제한다.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)

    event_id = db.Column(db.Integer, db.ForeignKey("events.id"), nullable=False, index=True)

    # 0.5 단위, 0.5~5.0
    rating = db.Column(db.Numeric(2, 1), nullable=False)

    content = db.Column(db.Text, nullable=False)

    # 저장소 키 목록(["reviews/<uuid>.webp", ...]). URL은 저장소를 옮겨도 바뀌지 않도록 응답 시점에 만든다.
    # 리뷰와 항상 함께 조회하고 장수가 적어 별도 테이블 대신 JSON 컬럼에 둔다.
    # 이미지 기능 이전 리뷰는 NULL이며 응답에서는 빈 목록으로 내려간다.
    images = db.Column(db.JSON, nullable=True)

    # API 검증을 우회한 입력에도 평점 범위와 0.5 단위를 보장하고,
    # 한 사용자가 한 행사에 리뷰를 하나만 쓰도록 DB에서 강제한다.
    __table_args__ = (
        db.CheckConstraint("rating >= 0.5 AND rating <= 5 AND rating * 2 = FLOOR(rating * 2)", name="ck_review_rating"),
        db.UniqueConstraint("user_id", "event_id", name="uq_review_user_event"),
    )