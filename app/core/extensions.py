"""Flask 확장 객체(db, migrate, jwt)를 앱 팩토리와 분리해 미리 만들어 두는 모듈.

앱 연결은 create_app()에서 init_app으로 한다. 다른 모듈이 app을 import하지 않고도
확장 객체를 쓸 수 있어 순환 import를 피할 수 있다.
"""
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
