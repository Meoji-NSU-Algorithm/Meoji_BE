"""카카오 서버와의 통신을 담당하는 클라이언트.

인가 코드를 카카오 access_token으로 교환하고 사용자 정보를 조회한다. DB와 서비스 JWT는 다루지 않는다.
"""
import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode

# 인증 서버(kauth)와 API 서버(kapi)의 도메인이 다르다.
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"

# 카카오가 응답하지 않을 때 워커가 무한정 대기하지 않도록 하는 최대 대기 시간(초).
# 초과하면 requests.Timeout이 발생하고 KAKAO_API_UNAVAILABLE(502)로 변환된다.
TIMEOUT = 5

def get_kakao_access_token(code: str) -> str:
    """인가 코드(code)를 카카오 access_token으로 교환한다.

    이 토큰은 카카오 사용자 정보 조회에만 쓰고 버리며, 클라이언트에 내려주는 서비스 JWT와는 별개다.

    Raises:
        BusinessException: 카카오와 통신하지 못하면 KAKAO_API_UNAVAILABLE,
            code 만료/재사용/redirect_uri 불일치 등으로 거부되면 KAKAO_TOKEN_REQUEST_FAILED.
    """
    data = {
        "grant_type": "authorization_code",
        "client_id": current_app.config["KAKAO_CLIENT_ID"],
        # 프론트가 authorize 요청에 쓴 redirect_uri와 반드시 같아야 한다.
        "redirect_uri": current_app.config["KAKAO_REDIRECT_URI"],
        "code": code,
    }
    # Client Secret은 카카오 콘솔에서 "사용함"으로 켠 경우에만 필요하다.
    client_secret = current_app.config.get("KAKAO_CLIENT_SECRET")
    if client_secret:
        data["client_secret"] = client_secret

    # 카카오 토큰 API는 JSON이 아니라 form-urlencoded를 받으므로 json= 이 아니라 data=를 쓴다.
    try:
        resp = requests.post(KAKAO_TOKEN_URL, data=data, timeout=TIMEOUT)
    except requests.RequestException:
        current_app.logger.warning("Kakao token request error", exc_info=True)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    if resp.status_code != 200:
        # 대부분 code 문제(만료/재사용/redirect_uri 불일치)라 클라이언트 쪽 원인으로 보고 401로 응답한다.
        # BusinessException은 전역 핸들러가 로그를 남기지 않으므로 카카오의 실패 원인(KOE006 등)은 여기서 남긴다.
        current_app.logger.warning("Kakao token request failed: %s", resp.text)
        raise BusinessException(ErrorCode.KAKAO_TOKEN_REQUEST_FAILED)

    try:
        return resp.json()["access_token"]
    except (ValueError, KeyError, TypeError):
        current_app.logger.warning("Kakao token response invalid: %s", resp.text)
        raise BusinessException(ErrorCode.KAKAO_TOKEN_REQUEST_FAILED)

def get_kakao_user_info(kakao_access_token: str) -> dict:
    """카카오 access_token으로 사용자 정보를 조회해 User 모델 필드명으로 변환한다.

    Returns:
        {"kakao_id": int, "email": str, "nickname": str, "profile_image": str | None}

    Raises:
        BusinessException: 통신 실패나 비정상 응답이면 KAKAO_API_UNAVAILABLE,
            이메일 등 필수 항목이 없으면 KAKAO_PROFILE_INVALID.
    """
    try:
        resp = requests.get(
            KAKAO_USER_INFO_URL,
            headers={"Authorization": f"Bearer {kakao_access_token}"},
            timeout=TIMEOUT,
        )
        # 방금 발급받은 토큰이므로 여기서 실패하면 클라이언트가 아니라 서버/카카오 쪽 문제다.
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError):
        # 네트워크 오류, 4xx/5xx(HTTPError), JSON이 아닌 응답
        current_app.logger.warning("Kakao user info request failed", exc_info=True)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    # 동의하지 않은 항목은 키 자체가 없을 수 있어, 필수 항목이 없으면 KAKAO_PROFILE_INVALID로 응답한다.
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

    # 프로필 사진은 선택 동의 항목이라 없을 수 있다.
    result["profile_image"] = profile.get("profile_image_url")
    return result
