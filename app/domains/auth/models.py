from datetime import datetime, timezone  # created_at에 넣을 UTC 시각 생성용

from app.core.extensions import db  # SQLAlchemy 확장 객체 (Column, Model 등 제공)

# 로그아웃되었거나 무효화된 JWT를 기록해두는 "블랙리스트" 테이블.
# JWT 자체는 서버가 강제로 만료시킬 수 없기 때문에(무상태 토큰),
# 로그아웃 시 해당 토큰의 jti(JWT ID)를 여기 저장해두고,
# 매 요청마다 "이 jti가 블록리스트에 있는가?"를 검사해서 로그아웃 처리를 흉내낸다.
class TokenBlocklist(db.Model):
    __tablename__ = 'token_blocklist'  # 실제 DB 테이블 이름

    id: int = db.Column(db.Integer, primary_key=True)  # 기본키(PK), 자동 증가

    # jti = JWT ID. 토큰 발급 시 각 토큰에 부여되는 고유 식별자(UUID 형태, 36자).
    # unique=True로 같은 jti가 중복 저장되지 않게 하고,
    # index=True로 요청마다 하는 "jti 존재 여부" 조회를 빠르게 만든다.
    jti: str = db.Column(db.String(36), unique=True, nullable=False, index=True)

    # 이 jti가 블록리스트에 등록된(=로그아웃/무효화된) 시각.
    # default=lambda: ... 로 INSERT 시점의 현재 UTC 시각이 자동으로 채워진다.
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )