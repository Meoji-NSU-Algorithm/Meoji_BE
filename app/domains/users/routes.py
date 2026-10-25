"""유저 API 라우트. 로그인/토큰은 auth 도메인이 맡고, 여기서는 유저 리소스 자체를 다룬다."""
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.core.response import CommonResponse
from app.domains.users.schemas import UserResponseSchema
from app.domains.users import service as user_service

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
