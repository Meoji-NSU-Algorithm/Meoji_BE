"""서비스 JWT의 발급, 재발급, 폐기를 담당하는 서비스.

유저 생성이나 카카오 통신은 모르고, 유저 id로 토큰을 만들고 폐기하는 일만 한다.
폐기는 jti를 TokenBlocklist에 저장하는 방식이며, 요청마다 jwt_callbacks.check_if_token_revoked가 이를 검사한다.
"""
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.auth.models import TokenBlocklist


def issue_tokens(user_id: int) -> dict[str, str]:
    """유저 id로 access/refresh 토큰 쌍을 발급한다.

    Returns:
        {"access_token", "refresh_token"}
    """
    # Flask-JWT-Extended 4.7+는 sub(identity)가 문자열이어야 한다. 사용할 때 int()로 되돌린다.
    identity = str(user_id)
    return {
        "access_token": create_access_token(identity=identity),
        "refresh_token": create_refresh_token(identity=identity),
    }

# SQLAlchemy 모델 생성자를 PyCharm이 인식하지 못해 나는 오탐을 끈다.
# noinspection PyArgumentList
def rotate_refresh_token(refresh_payload: dict) -> dict[str, str]:
    """사용한 refresh 토큰을 폐기하고 새 토큰 쌍을 발급한다 (Refresh Token Rotation).

    refresh 토큰을 일회용으로 만들어, 탈취된 토큰이 재사용되면 나중에 쓰는 쪽이 AUTH_TOKEN_REVOKED를 받게 한다.

    Args:
        refresh_payload: @jwt_required(refresh=True) 검증을 마친 refresh 토큰 payload.

    Raises:
        BusinessException: refresh 토큰이 아니면 AUTH_TOKEN_INVALID,
            동시 요청으로 이미 폐기된 토큰이면 AUTH_TOKEN_REVOKED.
    """
    # @jwt_required(refresh=True)가 막아 주지만, 서비스를 직접 호출해도 access 토큰으로 재발급되지 않게 한다.
    if refresh_payload.get("type") != "refresh":
        raise BusinessException(ErrorCode.AUTH_TOKEN_INVALID)

    # 블록리스트 확인은 동시 요청이 오면 둘 다 통과할 수 있다.
    # jti unique 제약 위반(IntegrityError)을 이미 사용된 토큰으로 처리해 중복 발급을 막는다.
    db.session.add(TokenBlocklist(jti=refresh_payload["jti"]))
    try:
        # 새 토큰을 주기 전에 폐기를 먼저 확정한다.
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise BusinessException(ErrorCode.AUTH_TOKEN_REVOKED)
    return issue_tokens(int(refresh_payload["sub"]))


# noinspection PyArgumentList
def revoke_jti(jti: str) -> None:
    """jti 하나를 블록리스트에 등록한다. 이미 폐기된 jti여도 오류 없이 넘어간다(멱등)."""
    # SAVEPOINT 안에서 저장해, unique 제약 위반이 나도 바깥 트랜잭션은 유지된다.
    try:
        with db.session.begin_nested():
            db.session.add(TokenBlocklist(jti=jti))
    except IntegrityError:
        pass
    db.session.commit()


# SQLAlchemy 모델 생성자를 PyCharm이 인식하지 못해 나는 오탐을 끈다.
# noinspection PyArgumentList
def revoke_tokens(access_payload: dict, refresh_token: str) -> None:
    """로그아웃: access(헤더)와 refresh(body) 토큰을 모두 블록리스트에 등록한다.

    Args:
        access_payload: @jwt_required()가 검증을 마친 access 토큰 payload.
        refresh_token: body로 받은 refresh 토큰 문자열. 검증된 적이 없어 여기서 검증한다.

    Raises:
        BusinessException: refresh 토큰이 아니거나 access 토큰 소유자와 다르면 AUTH_TOKEN_INVALID.
            서명이 위조된 토큰은 decode_token이 던진 예외를 jwt_callbacks가 같은 코드로 변환한다.
    """
    # allow_expired=True: 이미 만료된 refresh 토큰으로도 로그아웃할 수 있게 한다.
    # decode_token은 서명만 검증하고 블록리스트는 확인하지 않는다.
    refresh_payload = decode_token(refresh_token, allow_expired=True)

    # 서명이 정상이어도 type이 다르거나(access를 보냄) sub가 다르면(남의 토큰) 거부한다.
    # 남의 refresh 토큰을 폐기시키는 것을 막기 위해서다.
    if refresh_payload.get("type") != "refresh" or refresh_payload["sub"] != access_payload["sub"]:
        raise BusinessException(ErrorCode.AUTH_TOKEN_INVALID)

    # 토큰마다 SAVEPOINT 안에서 저장한다. 이미 폐기된 jti(중복 로그아웃, 동시 요청)는 unique 제약에 걸리지만
    # 그 토큰만 건너뛰고, 나머지 토큰은 계속 저장해 둘 다 폐기된 상태로 끝낸다.
    for jti in (access_payload["jti"], refresh_payload["jti"]):
        try:
            with db.session.begin_nested():
                db.session.add(TokenBlocklist(jti=jti))
        except IntegrityError:
            pass
    db.session.commit()
