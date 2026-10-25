# 인증 흐름을 "조율"하는 서비스. (오케스트레이터)
#
# 이 파일은 직접 DB를 만지거나 JWT를 만들지 않는다. 대신 역할별로 나뉜 서비스를
# 올바른 순서로 호출만 한다. 라우트(app/domains/auth/routes.py)는 이 파일의 함수만 호출한다.
#
#   kakao_auth_service : 카카오 서버와 통신 (code → 카카오 토큰 → 카카오 사용자 정보)
#   user_service       : 우리 DB의 User 조회/생성
#   token_service      : 우리 서비스의 JWT 발급/재발급/폐기
#
# [왜 이렇게 나눴나?]
#   - 나중에 구글/애플 로그인이 추가돼도 token_service, user_service는 그대로 재사용하고
#     여기에 login_with_google() 같은 함수만 추가하면 된다.
#   - JWT 정책(만료시간, 로테이션 등)을 바꿀 때는 token_service.py 한 파일만 보면 된다.
#   - 각 서비스가 서로를 모르기 때문에(카카오 서비스는 JWT를 모르고, 토큰 서비스는 카카오를 모름)
#     한 곳을 고쳐도 다른 곳이 깨질 일이 적다.
from app.domains.auth import kakao_client as kakao_auth_service, token_service
from app.domains.users import service as user_service


def login_with_kakao(code: str) -> dict:
    """카카오 인가 코드로 로그인한다. 처음 온 사용자면 회원가입까지 같이 처리한다.

    전체 흐름:
        프론트가 준 code
          → ① 카카오에 code를 주고 카카오 access_token을 받음
          → ② 카카오 access_token으로 카카오 사용자 정보(id, 이메일, 닉네임, 프로필) 조회
          → ③ 우리 DB에서 kakao_id로 유저를 찾고, 없으면 새로 생성(회원가입)
          → ④ 우리 서비스 전용 JWT(access/refresh) 발급

    ※ ①에서 받은 "카카오 access_token"은 사용자 정보 조회에만 한 번 쓰고 버린다.
      프론트에 내려주는 토큰은 ④에서 만든 "우리 서비스의 JWT"다. 둘을 헷갈리지 말 것.

    반환값: {"access_token": ..., "refresh_token": ..., "is_new_user": True/False}
    """
    # ① code → 카카오 access_token (code가 만료/재사용이면 여기서 KAKAO_TOKEN_REQUEST_FAILED 발생)
    kakao_token = kakao_auth_service.get_kakao_access_token(code)
    # ② 카카오 access_token → {"kakao_id", "email", "nickname", "profile_image"}
    info = kakao_auth_service.get_kakao_user_info(kakao_token)

    # ③ 우리 DB의 유저 조회/생성. is_new_user는 이번 요청에서 회원가입이 일어났는지 여부
    user, is_new_user = user_service.get_or_create_kakao_user(info)

    # ④ 우리 JWT 발급. `**`는 dict를 펼쳐서 합치는 문법:
    #   {**{"access_token": a, "refresh_token": r}, "is_new_user": True}
    #   → {"access_token": a, "refresh_token": r, "is_new_user": True}
    return {
        **token_service.issue_tokens(user.id),
        "is_new_user": is_new_user,
    }

def refresh(refresh_payload: dict) -> dict:
    """refresh 토큰으로 access/refresh 토큰 쌍을 새로 발급한다.

    refresh_payload: 라우트에서 get_jwt()로 꺼낸 refresh 토큰의 내용물
                     (서명/만료/블록리스트 검증은 @jwt_required(refresh=True)가 이미 끝낸 상태)
    """
    # 토큰 자체는 유효해도, 그 사이 유저가 탈퇴했을 수 있다.
    # 없는 유저에게 새 토큰을 발급하지 않도록 먼저 확인한다. (없으면 404 USER_NOT_FOUND)
    # "sub"는 토큰 발급 시 넣은 유저 id(문자열)라서 int()로 바꿔서 조회한다.
    user_service.get_user(int(refresh_payload["sub"]))
    return token_service.rotate_refresh_token(refresh_payload)

def logout(access_payload: dict, refresh_token: str) -> None:
    """로그아웃: 헤더의 access 토큰과 body의 refresh 토큰을 모두 폐기한다.

    access_payload: 라우트에서 get_jwt()로 꺼낸 access 토큰의 내용물 (이미 검증된 상태)
    refresh_token : body로 받은 refresh 토큰 "문자열" (아직 검증 전 → token_service에서 검증)
    """
    token_service.revoke_tokens(access_payload, refresh_token)
