# 카카오 서버와 직접 통신하는 코드만 모아둔 모듈.
# 우리 DB/JWT는 전혀 모르고, "code → 카카오 토큰 → 카카오 사용자 정보"까지만 책임진다.
#
# [카카오 로그인(OAuth 2.0 인가 코드 방식) 전체 흐름]
#   1) 프론트: 사용자를 카카오 로그인 페이지로 보낸다.
#        https://kauth.kakao.com/oauth/authorize?client_id=<REST API 키>&redirect_uri=<리다이렉트 URI>&response_type=code
#   2) 카카오: 로그인/동의가 끝나면 redirect_uri?code=XXXX 로 사용자를 돌려보낸다.
#   3) 프론트: 주소창의 code를 꺼내 우리 백엔드 POST /api/auth/kakao 로 보낸다.
#   4) 백엔드(이 파일): code → 카카오 access_token 교환 → 사용자 정보 조회
#
# [자주 나는 에러]
#   - KOE006 / invalid_grant: .env의 KAKAO_REDIRECT_URI가 1)에서 프론트가 쓴 redirect_uri와
#     한 글자라도 다르거나(끝의 / 포함), code를 이미 한 번 썼거나(일회용), 발급 후 약 10분이 지난 경우.
#     → 우리 서버는 401 KAKAO_TOKEN_REQUEST_FAILED로 응답하고, 서버 로그에 카카오의 원문 에러를 남긴다.
import requests  # 외부 HTTP API(카카오)를 호출하는 라이브러리
from flask import current_app  # 현재 실행 중인 Flask 앱. app.core.config 값(카카오 키 등)을 읽을 때 사용

from app.core.errors import BusinessException, ErrorCode

# 카카오 API 주소. 도메인이 다르다는 점에 주의 (kauth = 인증 서버, kapi = API 서버)
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"   # code → 카카오 토큰 교환
KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"  # 카카오 토큰 → 사용자 정보 조회

# 카카오가 응답하지 않을 때 워커가 무한정 대기하지 않도록 하는 최대 대기 시간(초).
# 초과하면 requests.Timeout이 발생하고, 아래 함수들이 KAKAO_API_UNAVAILABLE(502)로 바꾼다.
TIMEOUT = 5

def get_kakao_access_token(code: str) -> str:
    """프론트가 넘겨준 인가 코드(code)를 카카오 access_token으로 교환한다.

    ※ 여기서 받는 토큰은 "카카오의" 토큰이다. 사용자 정보 조회에만 쓰고 버리며,
      프론트에 내려주는 우리 서비스 JWT와는 별개다.
    """
    # 카카오 토큰 발급 API가 요구하는 파라미터
    data = {
        "grant_type": "authorization_code",                        # 인가 코드 방식이라는 고정값
        "client_id": current_app.config["KAKAO_CLIENT_ID"],        # 카카오 앱의 REST API 키
        "redirect_uri": current_app.config["KAKAO_REDIRECT_URI"],  # 프론트가 authorize 요청에 쓴 값과 반드시 동일해야 함
        "code": code,                                              # 프론트가 넘겨준 인가 코드
    }
    # 카카오 콘솔에서 Client Secret을 "사용함"으로 켰을 때만 필수
    # (.env에 값이 없으면 보내지 않는다)
    client_secret = current_app.config.get("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret

    # 카카오 토큰 API는 JSON이 아니라 form-urlencoded를 받는다 → json= 이 아니라 data=
    try:
        resp = requests.post(KAKAO_TOKEN_URL, data=data, timeout=TIMEOUT)
    except requests.RequestException:
        current_app.logger.warning("Kakao token request error", exc_info=True)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    if resp.status_code != 200:
        # 여기서 실패하는 건 대부분 code 문제(만료/재사용/redirect_uri 불일치) → 클라이언트 쪽 원인이라 401.
        # BusinessException은 전역 핸들러가 로그를 남기지 않으므로,
        # 카카오가 알려준 실패 원인(KOE006 등)은 여기서 직접 남긴다. (디버깅 시 서버 로그 확인)
        current_app.logger.warning("Kakao token request failed: %s", resp.text)
        raise BusinessException(ErrorCode.KAKAO_TOKEN_REQUEST_FAILED)

    # 응답 예: {"access_token": "...", "token_type": "bearer", "refresh_token": "...", "expires_in": 21599, ...}
    # 우리는 사용자 정보 조회용 access_token만 필요하다.
    try:
        return resp.json()["access_token"]
    except (ValueError, KeyError, TypeError):
        current_app.logger.warning("Kakao token response invalid: %s", resp.text)
        raise BusinessException(ErrorCode.KAKAO_TOKEN_REQUEST_FAILED)

def get_kakao_user_info(kakao_access_token: str) -> dict:
    """카카오 access_token으로 사용자 정보를 조회해서 우리 User 모델 필드명으로 변환한다.

    반환값: {"kakao_id": int, "email": str, "nickname": str, "profile_image": str | None}
    → user_service.get_or_create_kakao_user()에 그대로 전달된다.
    """
    try:
        resp = requests.get(
            KAKAO_USER_INFO_URL,
            headers={"Authorization": f"Bearer {kakao_access_token}"},  # 카카오 토큰을 Bearer 방식으로 전달
            timeout=TIMEOUT,
        )
        # 방금 발급받은 토큰이라 여기서 실패하면 클라이언트 잘못이 아니라 서버/카카오 쪽 문제.
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError):
        # 네트워크 오류, 4xx/5xx(HTTPError), JSON이 아닌 응답
        current_app.logger.warning("Kakao user info request failed", exc_info=True)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    # 카카오 응답 구조(필요한 부분만):
    # {
    #   "id": 1234567890,                       <- 카카오 회원번호 (불변, 우리 User.kakao_id)
    #   "kakao_account": {
    #     "email": "a@kakao.com",
    #     "profile": {"nickname": "홍길동", "profile_image_url": "https://..."}
    #   }
    # }
    # 이메일 등에 동의하지 않으면 키가 없을 수 있어, 없으면 KAKAO_PROFILE_INVALID로 응답한다.
    try:
        account = body["kakao_account"]
        profile = account["profile"]
        result = {
            "kakao_id": body["id"],
            "email": account["email"],
            "nickname": profile["nickname"],
        }
    except (KeyError, TypeError):
        raise BusinessException(ErrorCode.KAKAO_PROFILE_INVALID)

    # 카카오 응답의 필드명을 우리 User 모델의 필드명으로 바꿔서 반환한다.
    # 이렇게 하면 user_service는 카카오 응답 구조를 몰라도 된다.
    # 프로필 사진은 선택 동의라 없을 수 있다. (.get -> 없으면 None)
    result["profile_image"] = profile.get("profile_image_url")
    return result
