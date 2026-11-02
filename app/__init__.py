"""Flask 앱 팩토리. 확장 초기화, 오류 핸들러와 API Blueprint 등록을 담당한다."""
from flask import Flask
from app.core.config import Config, validate_required_config

from app.core.errors.handlers import register_error_handlers

from app.core.extensions import db, migrate, jwt

# 모델 클래스를 미리 로드해 둔다. Flask-Migrate가 autogenerate할 때
# db.Model 서브클래스가 import되어 있어야 테이블로 인식하기 때문이다.
from app import models


def create_app(config_class: type = Config) -> Flask:
    """Flask 앱을 생성한다.

    Args:
        config_class: app.config에 적용할 설정 클래스. 테스트에서는 테스트용 DB를 가리키는
            설정 클래스를 넘겨 운영/개발 DB와 분리한다.
    """
    app = Flask(__name__)

    app.config.from_object(config_class)

    # DB 연결 등 확장 초기화 전에 설정 누락을 잡아, 잘못된 설정으로는 부분 초기화된 앱이 생기지 않게 한다.
    validate_required_config(app)

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)

    # jwt_callbacks는 import되는 순간 데코레이터로 콜백이 jwt에 등록되므로 import 자체가 목적이다.
    # 빠지면 로그아웃된 토큰이 계속 통과하고 JWT 오류 응답도 공통 형식을 벗어난다.
    # 콜백 등록이 앱 생성 흐름에서 일어난다는 점이 드러나도록 create_app() 안에서 import한다.
    from app.core import jwt_callbacks  # noqa: F401

    register_error_handlers(app)
    register_blueprints(app)

    return app


def register_blueprints(app: Flask):
    """부모 Blueprint(api_bp)를 앱에 등록한다.

    새 도메인 Blueprint는 이 함수가 아니라 app/core/api.py에 추가한다.
    """
    # app.core.api가 각 도메인 routes를 거쳐 models까지 import하므로
    # app 패키지 초기화가 끝난 뒤(create_app 실행 시점)에 import해야 순환 import를 피한다.
    from app.core.api import api_bp

    app.register_blueprint(api_bp)
