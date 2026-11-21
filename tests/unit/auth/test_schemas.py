"""auth 스키마 단위 테스트."""
import pytest
from marshmallow import ValidationError

from app.domains.auth.schemas import KakaoLoginRequestSchema, LogoutRequestSchema, TokenResponseSchema


def test_kakao_login_valid():
    """code가 있으면 통과한다."""
    assert KakaoLoginRequestSchema().load({"code": "abc"}) == {"code": "abc"}


@pytest.mark.parametrize("data", [{}, {"code": ""}, {"code": None}, {"code": 123}])
def test_kakao_login_invalid(data):
    """code 누락/빈 문자열/None/숫자는 ValidationError이다."""
    with pytest.raises(ValidationError) as e:
        KakaoLoginRequestSchema().load(data)
    assert "code" in e.value.messages


def test_kakao_login_unknown_field_rejected():
    """알 수 없는 필드는 marshmallow 기본값에 따라 거부된다."""
    with pytest.raises(ValidationError):
        KakaoLoginRequestSchema().load({"code": "a", "extra": 1})


def test_logout_valid():
    """refresh_token이 있으면 통과한다."""
    assert LogoutRequestSchema().load({"refresh_token": "t"}) == {"refresh_token": "t"}


@pytest.mark.parametrize("data", [{}, {"refresh_token": ""}, {"refresh_token": None}])
def test_logout_invalid(data):
    """refresh_token 누락/빈 문자열/None은 ValidationError이다."""
    with pytest.raises(ValidationError) as e:
        LogoutRequestSchema().load(data)
    assert "refresh_token" in e.value.messages


def test_token_response_dump_full():
    """로그인 응답은 세 필드를 모두 포함한다."""
    out = TokenResponseSchema().dump({"access_token": "a", "refresh_token": "r", "is_new_user": True})
    assert out == {"access_token": "a", "refresh_token": "r", "is_new_user": True}


def test_token_response_dump_omits_missing_is_new_user():
    """재발급 응답에는 is_new_user 키가 없다."""
    out = TokenResponseSchema().dump({"access_token": "a", "refresh_token": "r"})
    assert out == {"access_token": "a", "refresh_token": "r"}


def test_token_response_dump_ignores_unknown_keys():
    """정의되지 않은 키는 응답에서 제외된다."""
    out = TokenResponseSchema().dump({"access_token": "a", "refresh_token": "r", "secret": "x"})
    assert "secret" not in out
