"""여러 도메인 모델이 공유하는 DB 믹스인."""
from datetime import datetime, timezone

from app.core.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """생성 시각(created_at)과 수정 시각(updated_at)을 UTC로 관리하는 믹스인.

    created_at과 updated_at은 INSERT 시 각각 현재 시각으로 채워진다(두 값이 마이크로초 단위로
    다를 수 있다). updated_at은 이후 UPDATE될 때마다 현재 시각으로 갱신된다.
    """

    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
