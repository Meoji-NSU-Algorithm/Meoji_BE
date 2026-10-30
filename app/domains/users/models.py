"""유저 도메인 모델."""
from app.core.db import TimestampMixin
from app.core.extensions import db

class User(TimestampMixin, db.Model):
    """카카오 로그인으로 가입한 유저."""
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    # 카카오 회원번호. 이메일과 달리 바뀌지 않아 로그인 시 유저 식별에 쓰므로 index를 건다.
    kakao_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)

    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    nickname = db.Column(db.String(50), nullable=False)
    profile_image = db.Column(db.String(500), nullable=True)

    # 필수 약관(서비스 이용약관, 개인정보 처리방침)에 동의한 시각. 동의 전에는 NULL이다.
    terms_agreed_at = db.Column(db.DateTime, nullable=True)
    privacy_agreed_at = db.Column(db.DateTime, nullable=True)

    # 마케팅 수신 동의(선택). server_default는 기존 유저 행에 NOT NULL 컬럼을 추가할 때 필요하다.
    marketing_agreed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("0"))
    # 마케팅 동의 시각. 철회하면 NULL로 비운다.
    marketing_agreed_at = db.Column(db.DateTime, nullable=True)
