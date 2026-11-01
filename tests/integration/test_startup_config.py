"""기동 시 필수 설정 검증 테스트. 잘못된 설정은 DB 초기화 전에 실패하므로 DB를 건드리지 않는다."""
import pytest

from app import create_app
from tests.conftest import TestConfig

REQUIRED = ["JWT_SECRET_KEY", "KAKAO_CLIENT_ID", "KAKAO_REDIRECT_URI", "SQLALCHEMY_DATABASE_URI"]


def _config(**overrides):
    return type("BadConfig", (TestConfig,), overrides)


@pytest.mark.parametrize("key", REQUIRED)
@pytest.mark.parametrize("bad", [None, "", "   ", "NEED_TO_SET", "need_to_set", "YOUR_KAKAO_ID", "CHANGE"])
def test_bad_required_value_raises(key, bad):
    """필수 키가 비었거나 자리표시 값이면 키 이름은 있고 값은 없는 메시지로 RuntimeError가 난다."""
    with pytest.raises(RuntimeError) as e:
        create_app(_config(**{key: bad}))
    msg = str(e.value)
    assert key in msg
    assert ".env.example" in msg
    if bad and bad.strip():
        assert bad not in msg


def test_multiple_bad_keys_reported_together():
    """문제 있는 키는 하나의 메시지에 모두 나열된다."""
    with pytest.raises(RuntimeError) as e:
        create_app(_config(JWT_SECRET_KEY=None, KAKAO_CLIENT_ID="YOUR_ID", KAKAO_REDIRECT_URI=""))
    msg = str(e.value)
    for key in ("JWT_SECRET_KEY", "KAKAO_CLIENT_ID", "KAKAO_REDIRECT_URI"):
        assert key in msg
    assert "SQLALCHEMY_DATABASE_URI" not in msg
    assert "YOUR_ID" not in msg


def test_optional_keys_not_required():
    """KAKAO_CLIENT_SECRET, TOURAPI_KEY가 없어도 기동된다."""
    assert create_app(_config(KAKAO_CLIENT_SECRET=None, TOURAPI_KEY=None)) is not None


def test_good_config_boots():
    assert create_app(TestConfig) is not None


def test_short_jwt_secret_warns_without_value(caplog):
    """짧은 JWT 비밀키는 기동은 허용하고 값 없이 경고만 남긴다."""
    secret = "short-secret-xyz"
    with caplog.at_level("WARNING"):
        app = create_app(_config(JWT_SECRET_KEY=secret))
    assert app is not None
    assert "JWT_SECRET_KEY" in caplog.text
    assert secret not in caplog.text
