from app.core.db import TimestampMixin  # created_at/updated_at 컬럼을 제공하는 믹스인
from app.core.extensions import db  # SQLAlchemy 확장 객체 (Column, Model 등 제공)

class User(TimestampMixin, db.Model):          # db.Model을 상속 → 이 클래스가 곧 "user" 테이블 매핑 모델
    __tablename__ = "user"     # 실제 DB 테이블 이름 지정

    id = db.Column(db.Integer, primary_key=True)  # 기본키(PK), 자동 증가

    # 카카오 로그인 식별자. unique=True(중복 불가), nullable=False(필수값),
    # index=True로 조회 속도를 위해 인덱스를 걸어둠 (로그인 시 kakao_id로 자주 검색하기 때문)
    kakao_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)

    # 이메일도 마찬가지로 중복 불가 + 필수 + 검색 빈도가 높아 인덱스 설정
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)

    nickname = db.Column(db.String(50), nullable=False)        # 닉네임, 필수값(nullable=False)
    profile_image = db.Column(db.String(500), nullable=True)       # 프로필 이미지 URL, 없어도 됨

