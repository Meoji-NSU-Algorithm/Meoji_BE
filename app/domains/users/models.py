"""유저 도메인 모델."""
from app.core.db import TimestampMixin
from app.core.extensions import db
from app.core.storage import object_url


class User(TimestampMixin, db.Model):
    """카카오 로그인으로 가입한 유저."""
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)

    # 카카오 회원번호. 이메일과 달리 바뀌지 않아 로그인 시 유저 식별에 쓰므로 index를 건다.
    kakao_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)

    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    nickname = db.Column(db.String(50), nullable=False)

    # 카카오 프로필 사진 URL. 로그인할 때마다 최신 값으로 갱신한다.
    # DB 컬럼 이름은 기존 그대로 profile_image라서 데이터 이전이 필요 없다.
    kakao_profile_image = db.Column("profile_image", db.String(500), nullable=True)

    # 화면에 보여줄 사진: kakao / custom / default. 로그인은 이 값을 바꾸지 않는다.
    # server_default는 기존 유저 행에 NOT NULL 컬럼을 추가할 때 필요하다.
    profile_image_source = db.Column(db.String(10), nullable=False, default="kakao", server_default="kakao")
    # 직접 올린 사진의 저장소 key(profiles/<uuid>.webp). custom일 때만 값이 있다.
    custom_profile_image_key = db.Column(db.String(100), nullable=True)

    # 필수 약관(서비스 이용약관, 개인정보 처리방침)에 동의한 시각. 동의 전에는 NULL이다.
    terms_agreed_at = db.Column(db.DateTime, nullable=True)
    privacy_agreed_at = db.Column(db.DateTime, nullable=True)

    # 마케팅 수신 동의(선택). server_default는 기존 유저 행에 NOT NULL 컬럼을 추가할 때 필요하다.
    marketing_agreed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.text("0"))
    # 마케팅 동의 시각. 철회하면 NULL로 비운다.
    marketing_agreed_at = db.Column(db.DateTime, nullable=True)

    @property
    def profile_image(self) -> str | None:
        """화면에 보여줄 프로필 사진 URL. 없으면 None이고 FE가 기본 이미지를 그린다."""
        if self.profile_image_source == "custom":
            return object_url(self.custom_profile_image_key)
        if self.profile_image_source == "default":
            return None
        return self.kakao_profile_image
