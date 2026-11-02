from datetime import datetime, timezone

from app.extensions import db


class Bookmark(db.Model):
    """사용자와 행사 사이의 북마크 저장 관계를 나타내는 모델."""

    __tablename__ = "bookmarks"

    # 각 행의 기본 키와 북마크를 만든 회원·대상 행사를 저장한다.
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    event_id = db.Column(db.Integer, db.ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    # 북마크 목록에서 연결된 행사 정보를 함께 읽을 수 있게 한다.
    event = db.relationship("Event")

    # 한 사용자가 같은 행사를 중복 저장하지 못하게 한다.
    __table_args__ = (
        db.UniqueConstraint("user_id", "event_id", name="uq_bookmarks_user_event"),
    )
