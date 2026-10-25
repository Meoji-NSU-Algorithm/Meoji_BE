"""인증 흐름을 조율하는 서비스.

kakao_client(카카오 통신), users.service(유저 조회/생성), token_service(JWT 발급/폐기)를
올바른 순서로 호출만 하며, 직접 DB를 다루거나 JWT를 만들지 않는다.
"""
from app.core.errors import BusinessException, ErrorCode
from app.domains.auth import kakao_client, token_service
from app.domains.users import service as user_service


def login_with_kakao(code: str) -> dict[str, str | bool]:
    """카카오 인가 코드로 로그인하고, 처음 온 사용자는 회원가입까지 처리한다.

    Returns:
        {"access_token", "refresh_token", "is_new_user"}
    """
    # 카카오 access_token은 사용자 정보 조회에만 쓰고 버린다. 클라이언트에는 우리 서비스 JWT를 내려준다.
    kakao_token = kakao_client.get_kakao_access_token(code)
    info = kakao_client.get_kakao_user_info(kakao_token)

    user, is_new_user = user_service.get_or_create_kakao_user(info)

    return {
        **token_service.issue_tokens(user.id),
        "is_new_user": is_new_user,
    }

def refresh(refresh_payload: dict) -> dict[str, str]:
    """refresh 토큰으로 access/refresh 토큰 쌍을 새로 발급한다.

    Args:
        refresh_payload: get_jwt()로 얻은 refresh 토큰 payload. 검증은 @jwt_required(refresh=True)가 끝낸 상태다.

    Raises:
        BusinessException: 유저가 없으면 AUTH_TOKEN_INVALID, 이미 사용한 토큰이면 AUTH_TOKEN_REVOKED.
    """
    # 토큰이 유효해도 그 사이 유저가 탈퇴했을 수 있어 먼저 확인한다. sub는 문자열 id다.
    try:
        user_service.get_user(int(refresh_payload["sub"]))
    except BusinessException as e:
        if e.error_code != ErrorCode.USER_NOT_FOUND:
            raise
        # 존재하지 않는 유저의 토큰은 더 이상 쓸 수 없는 토큰이므로 404가 아니라 401로 응답하고,
        # 재시도되지 않도록 제시된 refresh 토큰도 폐기한다.
        token_service.revoke_jti(refresh_payload["jti"])
        raise BusinessException(ErrorCode.AUTH_TOKEN_INVALID)
    return token_service.rotate_refresh_token(refresh_payload)

def logout(access_payload: dict, refresh_token: str) -> None:
    """헤더의 access 토큰과 body의 refresh 토큰을 모두 폐기한다.

    Args:
        access_payload: get_jwt()로 얻은 access 토큰 payload (검증 완료).
        refresh_token: body로 받은 refresh 토큰 문자열 (미검증, token_service에서 검증한다).
    """
    token_service.revoke_tokens(access_payload, refresh_token)
