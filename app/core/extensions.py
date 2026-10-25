# Flask 확장(extension) 객체들을 앱 팩토리(app/__init__.py의 create_app)와 분리해서
# 미리 생성해두는 모듈. 여기서는 인스턴스만 만들고, 실제 app과의 연결은
# create_app() 안에서 db.init_app(app) 등으로 이뤄진다.
# 이렇게 분리하면 모델/블루프린트 등 다른 모듈에서 app을 직접 import하지 않고도
# db, migrate, jwt를 가져다 쓸 수 있어 순환 import(circular import)를 피할 수 있다.
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

db = SQLAlchemy()       # DB ORM 확장 객체: 모델 정의, 세션/쿼리 등 DB 작업에 사용
migrate = Migrate()     # Flask-Migrate 확장 객체: Alembic 기반 DB 스키마 마이그레이션 관리
jwt = JWTManager()      # Flask-JWT-Extended 확장 객체: JWT 발급/검증 등 인증·인가 처리