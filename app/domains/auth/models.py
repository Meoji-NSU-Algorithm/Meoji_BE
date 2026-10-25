"""인증 도메인 모델. 로그아웃된 JWT를 기록하는 TokenBlocklist를 정의한다."""
from datetime import datetime, timezone

from app.core.extensions import db

class TokenBlocklist(db.Model):
    """폐기된 JWT의 jti를 저장하는 블록리스트.

    JWT는 서버가 강제로 만료시킬 수 없어서, 로그아웃/재발급 때 폐기할 토큰의 jti를 저장해 두고
    요청마다 블록리스트에 있는지 검사해 거부한다. (app/core/jwt_callbacks.py)
    """
    __tablename__ = "token_blocklist"

    id = db.Column(db.Integer, primary_key=True)

    # JWT ID(UUID 36자). unique로 중복 폐기를 막고, 요청마다 조회하므로 index를 건다.
    jti = db.Column(db.String(36), unique=True, nullable=False, index=True)

    # 블록리스트에 등록된 시각(UTC)
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
