"""Flask-JWT-Extended 콜백 모음.

JWT 오류 응답을 CommonResponse 형식으로 통일하고, 로그아웃된 토큰(TokenBlocklist)을 거부한다.
데코레이터는 import 시점에 등록되므로 create_app()에서 반드시 import해야 한다.
"""
from flask import jsonify

from app.core.extensions import jwt, db
from app.domains.auth.models import TokenBlocklist
from app.core.response import CommonResponse
from app.core.errors import ErrorCode


def _error(error_code: ErrorCode):
    """ErrorCode를 (JSON 응답, 상태 코드) 튜플로 만든다. BusinessException 핸들러와 같은 형식이다."""
    return jsonify(CommonResponse.error(error_code)), error_code.status_code


@jwt.token_in_blocklist_loader
def check_if_token_revoked(_jwt_header, jwt_payload) -> bool:
    """@jwt_required 요청마다 호출되며, True를 반환하면 revoked로 처리된다.

    로그아웃(token_service.revoke_tokens)이나 refresh 재발급(token_service.rotate_refresh_token) 때
    저장된 jti가 TokenBlocklist에 있는지 확인한다.
    """
    jti = jwt_payload["jti"]
    return db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar() is not None


# 아래 콜백의 `_` 접두 파라미터는 라이브러리가 위치 인자로 넘기는 값이라 지울 수 없다.

@jwt.unauthorized_loader
def missing_token_callback(_reason):
    """Authorization 헤더가 없을 때 401 AUTH_UNAUTHORIZED를 응답한다."""
    return _error(ErrorCode.AUTH_UNAUTHORIZED)


@jwt.invalid_token_loader
def invalid_token_callback(_reason):
    """서명 불일치, 형식 오류, 토큰 종류 불일치(access/refresh)일 때 401 AUTH_TOKEN_INVALID를 응답한다."""
    return _error(ErrorCode.AUTH_TOKEN_INVALID)


@jwt.expired_token_loader
def expired_token_callback(_jwt_header, _jwt_payload):
    """토큰이 만료되었을 때 401 AUTH_TOKEN_EXPIRED를 응답한다. refresh 토큰 만료도 같은 응답이다."""
    return _error(ErrorCode.AUTH_TOKEN_EXPIRED)


@jwt.revoked_token_loader
def revoked_token_callback(_jwt_header, _jwt_payload):
    """블록리스트에 등록된 토큰(로그아웃 또는 사용된 refresh 토큰)일 때 401 AUTH_TOKEN_REVOKED를 응답한다."""
    return _error(ErrorCode.AUTH_TOKEN_REVOKED)
