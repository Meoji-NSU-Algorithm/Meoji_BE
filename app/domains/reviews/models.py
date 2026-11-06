"""리뷰 ORM 모델."""

from datetime import datetime, timezone

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


class ReviewImageUpload(db.Model):
    """업로드했지만 아직 리뷰에 붙지 않은 이미지. 리뷰에 붙으면 행을 지운다.

    리뷰에 붙지 않은 채 오래된 행은 service.cleanup_unattached_uploads가 저장소 파일과 함께 지운다.
    리뷰 작성이 실패해 남은 업로드도 같은 방식으로 정리된다.
    """

    __tablename__ = "review_image_upload"

    # images.KEY_PATTERN 형식의 저장소 키(reviews/<uuid>.webp)
    key = db.Column(db.String(64), primary_key=True)

    # 업로드한 사용자. 탈퇴해도 정리 대상에서 빠지지 않도록 행은 남기고 NULL로 둔다.
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True)

    # 정리 기준 시각(UTC). 오래된 행부터 찾으므로 인덱스를 둔다.
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), index=True)
