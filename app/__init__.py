from flask import Flask  # Flask 앱 객체 생성
from app.core.config import Config  # JWT_SECRET_KEY, DB URI 등 환경설정 값을 담은 클래스

from app.core.errors.handlers import register_error_handlers  # 공통 오류 응답 핸들러 등록

from app.core.extensions import db, migrate, jwt  # DB/마이그레이션/JWT 확장 객체 (app에 바인딩할 예정)

# models 패키지를 import해서 User, TokenBlocklist 등 모델 클래스들을 로드시킴.
# 이 코드에서 직접 모델을 쓰지는 않지만, Flask-Migrate가 마이그레이션을 자동 생성할 때
# db.Model을 상속한 클래스들이 이미 import되어 있어야 인식할 수 있기 때문에 필요하다.
from app import models


def create_app(config_class: type = Config) -> Flask:
    """Flask 앱을 생성한다.

    Args:
        config_class: app.config에 적용할 설정 클래스. 테스트에서는 테스트용 DB를 가리키는
            설정 클래스를 넘겨서 운영/개발 DB와 분리한다. (기본값: Config)
    """
    app = Flask(__name__)

    app.config.from_object(config_class)  # 설정 클래스의 값들을 app.config에 적용

    db.init_app(app)          # extensions.py에서 만든 db 객체를 이 app에 연결
    migrate.init_app(app, db) # Alembic 마이그레이션이 이 app/db 조합을 쓰도록 연결
    jwt.init_app(app)         # JWT 인증 기능을 이 app에 연결

    # jwt_callbacks의 @jwt.xxx_loader 데코레이터는 모듈이 import되는 순간 jwt 객체에 등록된다.
    # 코드에서 직접 쓰지는 않지만 import 자체가 목적이다.
    # 이게 없으면 블록리스트 체크, JWT 에러 응답 포맷 통일이 전부 동작하지 않는다.
    # (로그아웃해도 토큰이 계속 통과되고, 에러 응답이 {"msg": "..."} 형태로 나가게 됨)
    # 함수 안에서 import하는 이유: 파일 맨 위에서 import하면 app 패키지가 아직 초기화 중이라
    # 순환 import 문제가 생길 수 있어서, create_app()이 실행되는 시점에 불러온다.
    # `# noqa: F401`은 "import해놓고 안 쓴다"는 린터 경고를 끄는 표시 (의도된 import라서).
    from app.core import jwt_callbacks  # noqa: F401

    register_error_handlers(app)  # 모든 도메인의 요청·DB·HTTP 오류를 공통 형식으로 처리
    register_blueprints(app)      # 인증·회원·리뷰·행사 API Blueprint를 등록

    return app


def register_blueprints(app: Flask):
    """모든 API 라우트를 앱에 등록한다.

    개별 Blueprint(auth_bp, users_bp, review_bp, events_bp 등)는 app/core/api.py의 부모 Blueprint(api_bp)에
    이미 묶여 있어서, 여기서는 api_bp 하나만 등록하면 된다.
    새 도메인 API를 추가할 때는 이 함수가 아니라 app/core/api.py를 수정한다.
    최종 URL 목록도 app/core/api.py 상단 주석에 정리되어 있다.
    """
    # 함수 안에서 import: app.core.api → routes → service → models로 연쇄 import되므로
    # app 패키지 초기화가 끝난 뒤(create_app 실행 시점)에 불러와야 순환 import가 안 난다.
    from app.core.api import api_bp

    app.register_blueprint(api_bp)
