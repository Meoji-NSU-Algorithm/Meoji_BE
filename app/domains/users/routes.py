"""유저 API 라우트. 로그인/토큰은 auth 도메인이 맡고, 여기서는 유저 리소스 자체를 다룬다."""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt

from app.core.response import CommonResponse
from app.domains.auth import service as auth_service
from app.domains.users.schemas import (
    UserResponseSchema,
    ConsentRequestSchema,
    ConsentResponseSchema,
    ProfileImageSourceRequestSchema,
)
from app.domains.users import service as user_service

# 부모 Blueprint(api_bp)가 /api를 붙인다.
users_bp = Blueprint("users", __name__, url_prefix="/users")


@users_bp.get("/me")
@jwt_required()
def get_user():
    """내 정보를 조회한다.

    GET /api/users/me
    Header: Authorization: Bearer <access_token>

    프론트는 로그인 직후 프로필 표시와 자동 로그인 시 토큰 유효성 확인에 사용한다.

    Returns:
        200: {"id", "email", "nickname", "profile_image"}

    Raises:
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED: 토큰 문제.
        404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    # sub는 문자열 유저 id이므로 int()로 변환한다. (token_service.issue_tokens 참고)
    user = user_service.get_user(int(get_jwt_identity()))

    return jsonify(CommonResponse.success(UserResponseSchema().dump(user))), 200


@users_bp.delete("/me")
@jwt_required()
def withdraw_user():
    """회원 탈퇴를 처리한다.

    DELETE /api/users/me
    Header: Authorization: Bearer <access_token>

    유저와 작성한 리뷰를 삭제하고, 사용한 access token을 폐기하며, 카카오 연결을 끊는다.
    카카오 연결 끊기에 실패해도 탈퇴는 그대로 완료된다.

    Returns:
        200: {"message": "회원 탈퇴가 완료되었습니다."}

    Raises:
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED: 토큰 문제.
        404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    # 탈퇴는 유저 삭제, 토큰 폐기, 카카오 연결 끊기를 묶는 흐름이라 auth.service가 조율한다.
    auth_service.withdraw(int(get_jwt_identity()), get_jwt()["jti"])

    return jsonify(CommonResponse.success(message="회원 탈퇴가 완료되었습니다.")), 200


@users_bp.get("/me/consents")
@jwt_required()
def get_consents():
    """내 약관 동의 현황을 조회한다.

    GET /api/users/me/consents
    Header: Authorization: Bearer <access_token>

    Returns:
        200: {"terms_agreed_at", "privacy_agreed_at", "marketing_agreed", "marketing_agreed_at"}
            동의 전이면 필수 약관 시각은 null이다.

    Raises:
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED: 토큰 문제.
        404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    user = user_service.get_user(int(get_jwt_identity()))

    return jsonify(CommonResponse.success(ConsentResponseSchema().dump(user))), 200


@users_bp.post("/me/consents")
@jwt_required()
def save_consents():
    """약관 동의를 저장한다.

    POST /api/users/me/consents
    Header: Authorization: Bearer <access_token>
    Body: {"terms": true, "privacy": true, "marketing": false}

    terms, privacy는 필수이며 true여야 한다. marketing은 선택이고 생략하면 false다.
    다시 호출해도 필수 약관의 최초 동의 시각은 유지되고, marketing은 바뀔 때만 갱신된다.

    Returns:
        200: {"terms_agreed_at", "privacy_agreed_at", "marketing_agreed", "marketing_agreed_at"}

    Raises:
        400 COMMON_INVALID_INPUT: 필수 약관에 동의하지 않았거나 요청 형식이 올바르지 않음.
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED: 토큰 문제.
        404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    data = ConsentRequestSchema().load(request.get_json(silent=True) or {})
    user = user_service.save_consent(int(get_jwt_identity()), data)

    return jsonify(CommonResponse.success(ConsentResponseSchema().dump(user))), 200


@users_bp.put("/me/profile-image")
@jwt_required()
def upload_profile_image():
    """프로필 사진을 직접 올린 사진으로 바꾼다.

    PUT /api/users/me/profile-image
    Header: Authorization: Bearer <access_token>
    Body: multipart/form-data, image 필드에 사진 한 장 (jpg/png/webp, 10MB 이하)

    Returns:
        200: {"id", "email", "nickname", "profile_image"}

    Raises:
        400 COMMON_INVALID_INPUT / IMAGE_INVALID: 사진이 없거나 2장 이상, 이미지가 아님.
        413 IMAGE_TOO_LARGE: 한 장 10MB 초과.
        503 IMAGE_STORAGE_UNAVAILABLE: 저장소 설정 누락 또는 통신 실패.
        401 AUTH_*: 토큰 문제. 404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    files = [file for file in request.files.getlist("image") if file.filename]
    user = user_service.set_custom_profile_image(int(get_jwt_identity()), files)

    return jsonify(CommonResponse.success(UserResponseSchema().dump(user))), 200


@users_bp.put("/me/profile-image/source")
@jwt_required()
def change_profile_image_source():
    """프로필 사진을 카카오 사진 또는 기본 이미지로 바꾼다. 직접 올린 사진 파일은 지운다.

    PUT /api/users/me/profile-image/source
    Header: Authorization: Bearer <access_token>
    Body: {"source": "kakao" | "default"}

    Returns:
        200: {"id", "email", "nickname", "profile_image"}

    Raises:
        400 COMMON_INVALID_INPUT: source가 kakao/default가 아님.
        401 AUTH_*: 토큰 문제. 404 USER_NOT_FOUND: 토큰은 유효하지만 유저가 DB에 없음.
    """
    data = ProfileImageSourceRequestSchema().load(request.get_json(silent=True) or {})
    user = user_service.set_profile_image_source(int(get_jwt_identity()), data["source"])

    return jsonify(CommonResponse.success(UserResponseSchema().dump(user))), 200
