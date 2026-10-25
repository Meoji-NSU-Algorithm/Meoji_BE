"""인증 API 라우트(카카오 로그인, 토큰 재발급, 로그아웃).

라우트는 요청 검증, 서비스 호출, 응답 생성만 맡는다. 예외는 전역 핸들러
(app/core/errors/handlers.py)와 JWT 콜백(app/core/jwt_callbacks.py)이 공통 형식으로 변환하므로
여기서는 try/except를 쓰지 않는다.
"""
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from app.core.response import CommonResponse
from app.domains.auth.schemas import KakaoLoginRequestSchema, LogoutRequestSchema, TokenResponseSchema
from app.domains.auth import service as auth_service

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.post("/kakao")
def kakao_login():
    """카카오 로그인. 처음 온 사용자는 회원가입까지 처리한다.

    POST /api/auth/kakao (인증 불필요)
    Body: {"code": "<카카오 인가 코드>"}

    Returns:
        200: {"access_token", "refresh_token", "is_new_user"}

    Raises:
        400 COMMON_INVALID_INPUT: code가 없거나 빈 문자열.
        401 KAKAO_TOKEN_REQUEST_FAILED: code 만료/재사용/redirect_uri 불일치.
        400 KAKAO_PROFILE_INVALID: 카카오 사용자 정보에 이메일 등 필수 항목이 없음.
        502 KAKAO_API_UNAVAILABLE: 카카오 서버와 통신 실패.
        409 USER_EMAIL_CONFLICT: 같은 이메일을 다른 카카오 계정이 사용 중.
    """
    # silent=True: JSON이 아니거나 비어 있어도 Flask가 자체 400을 던지지 않게 한다(공통 응답 형식 유지).
    # `or {}`: 스키마가 필드 단위 오류(COMMON_INVALID_INPUT)로 응답하게 빈 dict를 넘긴다.
    body = KakaoLoginRequestSchema().load(request.get_json(silent=True) or {})

    result = auth_service.login_with_kakao(body["code"])

    return jsonify(CommonResponse.success(TokenResponseSchema().dump(result))), 200

@auth_bp.post("/refresh")
# refresh=True: refresh 토큰만 허용한다. 서명, 만료, 블록리스트 검증도 이 데코레이터가 처리한다.
@jwt_required(refresh=True)
def refresh_token():
    """access/refresh 토큰을 재발급한다 (Refresh Token Rotation).

    POST /api/auth/refresh
    Header: Authorization: Bearer <refresh_token>

    Returns:
        200: {"access_token", "refresh_token"}. 사용한 refresh 토큰은 폐기되므로
            클라이언트는 새 refresh 토큰으로 교체해야 한다.

    Raises:
        401 AUTH_UNAUTHORIZED: Authorization 헤더 없음.
        401 AUTH_TOKEN_INVALID: 위조/형식 오류, 또는 access 토큰을 보냄.
        401 AUTH_TOKEN_EXPIRED: refresh 토큰 만료. 다시 로그인해야 한다.
        401 AUTH_TOKEN_REVOKED: 이미 사용했거나 로그아웃된 refresh 토큰.
        404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 없음.
    """
    # 서비스가 Flask 요청 객체에 의존하지 않도록 토큰 payload 값만 넘긴다.
    tokens = auth_service.refresh(get_jwt())

    # tokens에는 is_new_user가 없으므로 dump 결과에서 빠진다. (로그인과 같은 스키마 재사용)
    return jsonify(CommonResponse.success(TokenResponseSchema().dump(tokens))), 200

@auth_bp.post("/logout")
# 인자 없는 @jwt_required()는 access 토큰만 허용한다.
@jwt_required()
def logout():
    """로그아웃. access 토큰과 refresh 토큰을 모두 폐기한다.

    POST /api/auth/logout
    Header: Authorization: Bearer <access_token>
    Body: {"refresh_token": "<refresh 토큰>"}

    access만 폐기하면 남은 refresh로 새 access를 받을 수 있어 둘 다 블록리스트에 등록한다.

    Returns:
        200: data 없이 message만 반환한다.

    Raises:
        400 COMMON_INVALID_INPUT: body에 refresh_token 없음.
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED:
            access 토큰 문제. body의 refresh 토큰이 위조되었거나 본인 것이 아니어도 AUTH_TOKEN_INVALID.
    """
    body = LogoutRequestSchema().load(request.get_json(silent=True) or {})

    auth_service.logout(get_jwt(), body["refresh_token"])

    return jsonify(CommonResponse.success(message="로그아웃 되었습니다.")), 200
