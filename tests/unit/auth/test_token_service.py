"""token_service 단위 테스트 (실제 테스트 DB 블록리스트 사용)."""
import pytest
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from jwt import DecodeError
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.auth import token_service
from app.domains.auth.models import TokenBlocklist


def _blocked(jti):
    return db.session.scalar(db.select(TokenBlocklist.id).filter_by(jti=jti)) is not None


def test_issue_tokens_claims(app_ctx):
    """access/refresh 토큰이 올바른 sub(문자열)/type 클레임을 가지고 jti가 서로 다르다."""
    t = token_service.issue_tokens(7)
    a, r = decode_token(t["access_token"]), decode_token(t["refresh_token"])
    assert a["sub"] == "7" and a["type"] == "access"
    assert r["sub"] == "7" and r["type"] == "refresh"
    assert a["jti"] != r["jti"]


def test_issue_tokens_unique_each_call(app_ctx):
    """호출마다 새로운 jti가 발급된다."""
    a = decode_token(token_service.issue_tokens(1)["refresh_token"])
    b = decode_token(token_service.issue_tokens(1)["refresh_token"])
    assert a["jti"] != b["jti"]


def test_rotate_blocklists_old_and_issues_new(app_ctx):
    """유효 refresh는 jti를 블록리스트에 넣고 같은 유저의 새 토큰 쌍을 반환한다."""
    old = decode_token(token_service.issue_tokens(5)["refresh_token"])
    new = token_service.rotate_refresh_token(old)
    assert _blocked(old["jti"])
    assert decode_token(new["access_token"])["sub"] == "5"
    new_r = decode_token(new["refresh_token"])
    assert new_r["jti"] != old["jti"] and new_r["type"] == "refresh"
    assert not _blocked(new_r["jti"])


def test_rotate_reuse_raises_revoked(app_ctx):
    """같은 refresh를 두 번 쓰면 AUTH_TOKEN_REVOKED이고 세션은 계속 사용 가능하다."""
    old = decode_token(token_service.issue_tokens(5)["refresh_token"])
    token_service.rotate_refresh_token(old)
    with pytest.raises(BusinessException) as e:
        token_service.rotate_refresh_token(old)
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_REVOKED
    assert db.session.scalar(db.select(db.func.count()).select_from(TokenBlocklist)) == 1


def test_rotate_integrity_error_on_commit(app_ctx, monkeypatch):
    """commit 시 IntegrityError는 AUTH_TOKEN_REVOKED로 변환되고 새 토큰은 발급되지 않는다."""
    old = decode_token(token_service.issue_tokens(5)["refresh_token"])
    called = []
    monkeypatch.setattr(token_service, "issue_tokens", lambda uid: called.append(uid))

    def boom():
        raise IntegrityError("s", {}, Exception("dup"))
    monkeypatch.setattr(db.session, "commit", boom)
    with pytest.raises(BusinessException) as e:
        token_service.rotate_refresh_token(old)
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_REVOKED
    assert called == []


@pytest.mark.xfail(strict=True, reason="BUG(low): token_service.py rotate_refresh_token does not check payload type==refresh; relies solely on route decorator")
def test_rotate_rejects_access_payload(app_ctx):
    """서비스 계층에서 access payload를 refresh로 넘기면 거부되어야 한다(방어적 검증)."""
    access = decode_token(token_service.issue_tokens(5)["access_token"])
    with pytest.raises(BusinessException):
        token_service.rotate_refresh_token(access)


def test_revoke_blocklists_both(app_ctx):
    """로그아웃은 access/refresh jti를 모두 블록리스트에 넣는다."""
    t = token_service.issue_tokens(3)
    a, r = decode_token(t["access_token"]), decode_token(t["refresh_token"])
    token_service.revoke_tokens(a, t["refresh_token"])
    assert _blocked(a["jti"]) and _blocked(r["jti"])


@pytest.mark.xfail(strict=True, reason="BUG: token_service.py:79 autoflush of pending access jti raises uncaught IntegrityError at the select (outside try) when access jti already blocklisted")
def test_revoke_idempotent(app_ctx):
    """같은 토큰으로 두 번 로그아웃해도 예외 없이 행이 중복되지 않는다."""
    t = token_service.issue_tokens(3)
    a = decode_token(t["access_token"])
    token_service.revoke_tokens(a, t["refresh_token"])
    token_service.revoke_tokens(a, t["refresh_token"])
    assert db.session.scalar(db.select(db.func.count()).select_from(TokenBlocklist)) == 2


def test_revoke_with_already_rotated_refresh(app_ctx):
    """/refresh에서 이미 폐기된 refresh로 로그아웃해도 access는 폐기된다."""
    t = token_service.issue_tokens(3)
    a, r = decode_token(t["access_token"]), decode_token(t["refresh_token"])
    token_service.rotate_refresh_token(r)
    token_service.revoke_tokens(a, t["refresh_token"])
    assert _blocked(a["jti"]) and _blocked(r["jti"])


@pytest.mark.xfail(strict=True, reason="BUG: token_service.py:79 same autoflush IntegrityError escapes the try/except")
def test_revoke_access_already_blocklisted_still_revokes_refresh(app_ctx):
    """access jti가 이미 폐기된 경쟁 상황에서도 refresh는 폐기되어야 한다."""
    t = token_service.issue_tokens(3)
    a, r = decode_token(t["access_token"]), decode_token(t["refresh_token"])
    db.session.add(TokenBlocklist(jti=a["jti"]))
    db.session.commit()
    token_service.revoke_tokens(a, t["refresh_token"])
    assert _blocked(r["jti"])


def test_revoke_rejects_access_token_as_refresh(app_ctx):
    """body에 access 토큰을 넣으면 AUTH_TOKEN_INVALID이고 아무것도 폐기되지 않는다."""
    t = token_service.issue_tokens(3)
    a = decode_token(t["access_token"])
    with pytest.raises(BusinessException) as e:
        token_service.revoke_tokens(a, t["access_token"])
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_INVALID
    assert db.session.scalar(db.select(db.func.count()).select_from(TokenBlocklist)) == 0


def test_revoke_rejects_other_users_refresh(app_ctx):
    """다른 유저의 refresh 토큰은 AUTH_TOKEN_INVALID이다."""
    mine = decode_token(token_service.issue_tokens(1)["access_token"])
    other = token_service.issue_tokens(2)["refresh_token"]
    with pytest.raises(BusinessException) as e:
        token_service.revoke_tokens(mine, other)
    assert e.value.error_code == ErrorCode.AUTH_TOKEN_INVALID
    assert db.session.scalar(db.select(db.func.count()).select_from(TokenBlocklist)) == 0


def test_revoke_accepts_expired_refresh(app_ctx):
    """만료된 refresh로도 로그아웃할 수 있다."""
    from datetime import timedelta
    expired = create_refresh_token(identity="3", expires_delta=timedelta(seconds=-10))
    a = decode_token(token_service.issue_tokens(3)["access_token"])
    token_service.revoke_tokens(a, expired)
    assert _blocked(decode_token(expired, allow_expired=True)["jti"])


def test_revoke_garbage_refresh_raises_decode_error(app_ctx):
    """형식이 깨진 refresh는 decode 예외가 전파된다(라우트에서 jwt 핸들러가 변환)."""
    a = decode_token(token_service.issue_tokens(3)["access_token"])
    with pytest.raises(Exception) as e:
        token_service.revoke_tokens(a, "not.a.jwt")
    assert not isinstance(e.value, BusinessException)
