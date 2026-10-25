from datetime import datetime, timezone  # created_at/updated_at에 넣을 UTC 시각 생성용

from app.core.extensions import db  # SQLAlchemy 확장 객체 (Column, Model 등 제공)

class User(db.Model):          # db.Model을 상속 → 이 클래스가 곧 'user' 테이블 매핑 모델
    __tablename__ = 'user'     # 실제 DB 테이블 이름 지정

    id: int = db.Column(db.Integer, primary_key=True)  # 기본키(PK), 자동 증가

    # 카카오 로그인 식별자. unique=True(중복 불가), nullable=False(필수값),
    # index=True로 조회 속도를 위해 인덱스를 걸어둠 (로그인 시 kakao_id로 자주 검색하기 때문)
    kakao_id: int = db.Column(db.BigInteger, unique=True, nullable=False, index=True)

    # 이메일도 마찬가지로 중복 불가 + 필수 + 검색 빈도가 높아 인덱스 설정
    email: str = db.Column(db.String(255), unique=True, nullable=False, index=True)

    nickname: str = db.Column(db.String(50), nullable=False)        # 닉네임, 필수값(nullable=False)
    profile_image = db.Column(db.String(500), nullable=True)       # 프로필 이미지 URL, 없어도 됨


    # 레코드 생성 시각. default=lambda: ... 는 INSERT할 때 값이 없으면
    # 이 함수를 호출해 현재 UTC 시각을 자동으로 채워 넣으라는 뜻
    created_at: datetime = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    # 레코드 마지막 수정 시각. default는 최초 생성 시 created_at과 동일하게 채워지고,
    # onupdate=lambda: ... 는 이후 이 row가 UPDATE될 때마다 자동으로 현재 UTC 시각으로 갱신하라는 뜻
    updated_at: datetime = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )