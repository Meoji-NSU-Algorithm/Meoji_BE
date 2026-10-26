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
