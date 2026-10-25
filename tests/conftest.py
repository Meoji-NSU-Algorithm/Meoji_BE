"""테스트 공통 설정.

개발 DB와 분리된 전용 DB(`<개발DB이름>_test_<프로세스ID>`)를 세션 시작 시 만들고, 세션이 끝나면 삭제한다.
프로세스ID를 붙여서 pytest를 동시에 여러 개 실행해도 서로의 DB를 지우지 않는다.
접속 정보는 .env의 SQLALCHEMY_DATABASE_URI에서 DB 이름만 바꿔서 사용한다.
DB 이름에 `_test_`가 없으면 데이터 보호를 위해 테스트를 중단한다.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import create_app
from app.core.config import Config
from app.core.extensions import db


def _test_db_url():
    if not Config.SQLALCHEMY_DATABASE_URI:
        pytest.exit(".env 에 SQLALCHEMY_DATABASE_URI 가 없어 테스트 DB 를 만들 수 없습니다.", returncode=2)
    base = make_url(Config.SQLALCHEMY_DATABASE_URI)
    return base.set(database=f"{base.database}_test_{os.getpid()}")


class TestConfig(Config):
    __test__ = False  # pytest가 테스트 클래스로 수집하지 않도록 한다.
    TESTING = True
    SQLALCHEMY_DATABASE_URI = _test_db_url().render_as_string(hide_password=False)
    JWT_SECRET_KEY = "test-secret-key-for-unit-tests-only-32b"
    TOURAPI_KEY = "test-tourapi-key"
    KAKAO_CLIENT_ID = "test-kakao-client"
    KAKAO_CLIENT_SECRET = None
    KAKAO_REDIRECT_URI = "http://localhost/callback"


@pytest.fixture(scope="session")
def app():
    url = _test_db_url()
    if "_test_" not in url.database:
        pytest.exit("테스트 DB 이름에 _test_ 가 없어 중단합니다.", returncode=2)

    server_url = url._replace(database=None)
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
        conn.execute(text(f"CREATE DATABASE `{url.database}` CHARACTER SET utf8mb4"))

    flask_app = create_app(TestConfig)
    with flask_app.app_context():
        db.create_all()

    yield flask_app

    with flask_app.app_context():
        db.session.remove()
        db.engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS `{url.database}`"))
    admin.dispose()


@pytest.fixture()
def app_ctx(app):
    """테스트마다 모든 테이블을 비우고 앱 컨텍스트를 제공한다."""
    with app.app_context():
        db.session.remove()
        with db.engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            for table in reversed(db.metadata.sorted_tables):
                conn.execute(table.delete())
            conn.execute(text("SET FOREIGN_KEY_CHECKS=1"))
        yield app
        db.session.remove()


@pytest.fixture()
def client(app_ctx):
    return app_ctx.test_client()
