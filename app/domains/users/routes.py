# 유저(users) 관련 API 라우트 모음. (Spring의 UserController 역할)
# 인증(로그인/토큰)은 app/domains/auth/routes.py, "유저라는 리소스 자체"에 대한 API는 여기에 둔다.
# 나중에 닉네임 수정(PATCH /api/users/me), 회원 탈퇴(DELETE /api/users/me) 등이 여기에 추가된다.
from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.core.response import CommonResponse
from app.domains.users.schemas import UserResponseSchema
from app.domains.users import service as user_service

# 부모 Blueprint(api_bp)가 "/api"를 붙여주므로 최종 경로는 /api/users/... 가 된다.
users_bp = Blueprint("users", __name__, url_prefix="/users")

@users_bp.get("/me")
# access 토큰이 있어야만 호출 가능. 없거나/만료/위조/로그아웃된 토큰이면
# 이 함수 안으로 들어오기 전에 app/core/jwt_callbacks.py의 콜백이 401을 응답한다.
@jwt_required()
def get_user():
    """내 정보 조회

    GET /api/users/me
    인증 헤더: Authorization: Bearer <access_token>

    [어디에 쓰이나?]
        로그인 응답에는 토큰만 있고 닉네임/프로필 사진은 없다. 프론트는 이 API로
        1) 로그인 직후: 헤더에 "OO님", 프로필 사진 표시
        2) 앱 재실행/새로고침 시(자동 로그인): 저장해 둔 토큰이 아직 유효한지 확인
           - 200이면 로그인 상태 유지
           - 401 AUTH_TOKEN_EXPIRED면 /api/auth/refresh 시도 → 그것도 실패하면 로그인 화면으로
        또한 백엔드 개발 중 "JWT가 제대로 동작하나?"를 확인하는 가장 간단한 테스트용 API이기도 하다.

    성공 응답 (200):
        {"success": true, "message": "OK",
         "data": {"id": 1, "email": "a@kakao.com", "nickname": "홍길동", "profile_image": "https://..." 또는 null}}

    실패 응답:
        401 AUTH_UNAUTHORIZED / AUTH_TOKEN_INVALID / AUTH_TOKEN_EXPIRED / AUTH_TOKEN_REVOKED
        404 USER_NOT_FOUND : 토큰은 유효하지만 유저가 탈퇴 등으로 DB에 없음
    """
    # get_jwt_identity(): 토큰 payload의 "sub"(= 토큰 발급 시 넣은 identity) 값을 꺼낸다.
    #   토큰 발급 시(token_service.issue_tokens) 유저 id를 문자열로 넣었기 때문에
    #   (Flask-JWT-Extended 4.7+는 sub가 문자열이어야 함) 여기서 int()로 다시 숫자로 바꿔서 조회한다.
    user = user_service.get_user(int(get_jwt_identity()))

    # UserResponseSchema에 정의한 필드(id, email, nickname, profile_image)만 응답에 담긴다.
    # kakao_id, created_at 같은 내부 정보는 자동으로 빠진다.
    return jsonify(CommonResponse.success(UserResponseSchema().dump(user))), 200
