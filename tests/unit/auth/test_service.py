"""auth.service 단위 테스트. kakao_client만 monkeypatch하고 DB는 실제 사용한다."""
import pytest
from flask_jwt_extended import decode_token

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.auth import kakao_client, service, token_service
from app.domains.auth.models import TokenBlocklist
from app.domains.users.models import User

INFO = {"kakao_id": 555, "email": "k@b.com", "nickname": "kk", "profile_image": None}


@pytest.fixture()
def fake_kakao(monkeypatch):
    calls = {}

    def tok(code):
        calls["code"] = code
        return "KAKAO_TOKEN"

    def info(t):
        calls["token"] = t
        return dict(INFO)

    monkeypatch.setattr(kakao_client, "get_kakao_access_token", tok)
    monkeypatch.setattr(kakao_client, "get_kakao_user_info", info)
    return calls


def test_login_new_user(app_ctx, fake_kakao):
    """신규 로그인은 가입 후 토큰과 is_new_user=True를 반환한다."""
    res = service.login_with_kakao("CODE")
    assert fake_kakao == {"code": "CODE", "token": "KAKAO_TOKEN"}
    assert res["is_new_user"] is True
    user = db.session.scalar(db.select(User).filter_by(kakao_id=555))
    assert decode_token(res["access_token"])["sub"] == str(user.id)
    assert decode_token(res["refresh_token"])["type"] == "refresh"


def test_login_existing_user(app_ctx, fake_kakao):
    """재로그인은 is_new_user=False이고 유저가 늘지 않는다."""
    service.login_with_kakao("CODE")
    res = service.login_with_kakao("CODE")
    assert res["is_new_user"] is False
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 1


def test_login_kakao_failure_propagates_and_creates_nothing(app_ctx, monkeypatch):
    """카카오 토큰 교환 실패 시 예외가 전파되고 유저가 생성되지 않는다."""
    def fail(code):
        raise BusinessException(ErrorCode.KAKAO_TOKEN_REQUEST_FAILED)
    monkeypatch.setattr(kakao_client, "get_kakao_access_token", fail)
    with pytest.raises(BusinessException) as e:
        service.login_with_kakao("X")
    assert e.value.error_code == ErrorCode.KAKAO_TOKEN_REQUEST_FAILED
    assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0


def test_login_email_conflict(app_ctx, fake_kakao, monkeypatch):
    """다른 kakao_id가 같은 이메일을 쓰면 USER_EMAIL_CONFLICT이다."""
    service.login_with_kakao("CODE")
    monkeypatch.setattr(kakao_client, "get_kakao_user_info", lambda t: {**INFO, "kakao_id": 999})
    with pytest.raises(BusinessException) as e:
        service.login_with_kakao("CODE")
    assert e.value.error_code == ErrorCode.USER_EMAIL_CONFLICT


def test_refresh_success(app_ctx, fake_kakao):
    """유효한 payload로 새 토큰을 받고 옛 jti는 폐기되며 is_new_user는 없다."""
    res = service.login_with_kakao("CODE")
    payload = decode_token(res["refresh_token"])
    new = service.refresh(payload)
    assert set(new) == {"access_token", "refresh_token"}
    assert db.session.scalar(db.select(TokenBlocklist.id).filter_by(jti=payload["jti"])) is not None


def test_refresh_user_deleted(app_ctx):
    """유저가 없으면 AUTH_TOKEN_INVALID(401)이고 제시된 refresh는 폐기되어 재시도해도 같은 결과다."""
    payload = decode_token(token_service.issue_tokens(4040)["refresh_token"])
    with pytest.raises(BusinessException) as e:
        service.refresh(payload)
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_INVALID
    assert db.session.scalar(db.select(TokenBlocklist.id).filter_by(jti=payload["jti"])) is not None
    # 이미 폐기된 jti여도 멱등이라 500 없이 같은 오류가 반환된다.
    with pytest.raises(BusinessException) as e2:
        service.refresh(payload)
    assert e2.value.error_code == ErrorCode.AUTH_TOKEN_INVALID


def test_refresh_reuse_revoked(app_ctx, fake_kakao):
    """같은 refresh payload 재사용은 AUTH_TOKEN_REVOKED이다."""
    payload = decode_token(service.login_with_kakao("CODE")["refresh_token"])
    service.refresh(payload)
    with pytest.raises(BusinessException) as e:
        service.refresh(payload)
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_REVOKED


def test_logout_revokes_both(app_ctx, fake_kakao):
    """logout은 access/refresh를 모두 블록리스트에 넣는다."""
    res = service.login_with_kakao("CODE")
    a = decode_token(res["access_token"])
    service.logout(a, res["refresh_token"])
    r = decode_token(res["refresh_token"])
    for jti in (a["jti"], r["jti"]):
        assert db.session.scalar(db.select(TokenBlocklist.id).filter_by(jti=jti)) is not None
