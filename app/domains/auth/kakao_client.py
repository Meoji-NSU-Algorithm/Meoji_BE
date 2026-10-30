"""카카오 서버와의 통신을 담당하는 클라이언트.

인가 코드를 카카오 access_token으로 교환하고 사용자 정보를 조회하고, 회원 탈퇴 시 카카오 연결을 끊는다. DB와 서비스 JWT는 다루지 않는다.

토큰 교환 실패는 원인에 따라 나눈다. 사용자가 다시 로그인하면 해결되는 인가 코드 문제만 401,
우리 서버의 카카오 설정 오류나 카카오 장애처럼 사용자가 해결할 수 없는 문제는 502로 응답한다.
"""
import requests
from flask import current_app

from app.core.errors import BusinessException, ErrorCode

# 인증 서버(kauth)와 API 서버(kapi)의 도메인이 다르다.
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"
KAKAO_UNLINK_URL = "https://kapi.kakao.com/v1/user/unlink"

# 카카오가 응답하지 않을 때 워커가 무한정 대기하지 않도록 하는 최대 대기 시간(초).
# 초과하면 requests.Timeout이 발생하고 KAKAO_API_UNAVAILABLE(502)로 변환된다.
TIMEOUT = 5

# 우리 서버의 Client ID/Secret 설정이 틀렸을 때 카카오가 돌려주는 값. 사용자의 code 문제가 아니다.
_SERVER_CONFIG_ERRORS = {"invalid_client", "unauthorized_client"}
_SERVER_CONFIG_ERROR_CODES = {"KOE010", "KOE101"}
_LOG_FIELD_MAX = 200


def _log_value(value) -> str:
    """로그에 남길 값을 문자열로 바꾸고 길이를 제한한다."""
    return str(value)[:_LOG_FIELD_MAX]


def _parse_error_body(resp) -> dict | None:
    """카카오 오류 응답을 dict로 파싱한다. JSON이 아니거나 dict가 아니면 None."""
    try:
        body = resp.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def get_kakao_access_token(code: str) -> str:
    """인가 코드(code)를 카카오 access_token으로 교환한다.

    이 토큰은 카카오 사용자 정보 조회에만 쓰고 버리며, 클라이언트에 내려주는 서비스 JWT와는 별개다.

    Raises:
        BusinessException: code 만료/재사용/redirect_uri 불일치 등 클라이언트 쪽 4xx(429 제외)면
            KAKAO_TOKEN_REQUEST_FAILED(401). 통신 실패, 5xx, 429, JSON이 아닌 오류 본문,
            서버 설정 오류(invalid_client/unauthorized_client, KOE010/KOE101),
            access_token 없는 200 응답은 KAKAO_API_UNAVAILABLE(502).
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
        _raise_token_error(resp)

    # 200인데 access_token이 없으면 클라이언트 잘못이 아니라 카카오 응답 이상이다.
    try:
        token = resp.json().get("access_token")
    except (ValueError, AttributeError):
        token = None
    if not isinstance(token, str) or not token:
        current_app.logger.error("Kakao token response invalid: status=%s", resp.status_code)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)
    return token


def _raise_token_error(resp) -> None:
    """200이 아닌 토큰 응답을 원인별 BusinessException으로 변환한다.

    BusinessException은 전역 핸들러가 로그를 남기지 않으므로 원인(KOE006 등)은 여기서 남긴다.
    로그에는 status/error/error_code/error_description만 남기고 원문 body와 토큰은 남기지 않는다.
    """
    status = resp.status_code
    body = _parse_error_body(resp)
    if body is None:
        # JSON이 아닌 오류 본문은 게이트웨이/장애 응답일 가능성이 높다.
        current_app.logger.warning("Kakao token request failed: status=%s (non-JSON body)", status)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    # 예상 밖 타입(list 등)이 와도 set 멤버십 검사에서 TypeError가 나지 않도록 문자열만 인정한다.
    error = body.get("error")
    error_code = body.get("error_code")
    error_key = error if isinstance(error, str) else None
    error_code_key = error_code if isinstance(error_code, str) else None
    fields = (_log_value(status), _log_value(error), _log_value(error_code),
              _log_value(body.get("error_description")))

    if error_key in _SERVER_CONFIG_ERRORS or error_code_key in _SERVER_CONFIG_ERROR_CODES:
        current_app.logger.error(
            "Kakao 설정 오류(KAKAO_CLIENT_ID/KAKAO_CLIENT_SECRET 확인 필요): "
            "status=%s error=%s error_code=%s error_description=%s", *fields)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    if status >= 500 or status == 429:
        current_app.logger.warning(
            "Kakao token request unavailable: status=%s error=%s error_code=%s error_description=%s", *fields)
        raise BusinessException(ErrorCode.KAKAO_API_UNAVAILABLE)

    # 나머지 4xx는 code 만료/재사용/redirect_uri 불일치 등 클라이언트 쪽 원인이다.
    current_app.logger.warning(
        "Kakao token request failed: status=%s error=%s error_code=%s error_description=%s", *fields)
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


def unlink_kakao_user(kakao_id: int) -> None:
    """카카오 계정과 서비스의 연결을 끊는다.

    회원 탈퇴가 commit된 뒤에 호출하며, 실패해도 예외를 던지지 않고 경고 로그만 남긴다.
    Admin 키는 서버에서만 쓰고 클라이언트에 노출하면 안 된다.
    """
    admin_key = current_app.config.get("KAKAO_ADMIN_KEY")
    if not admin_key:
        current_app.logger.warning("KAKAO_ADMIN_KEY 미설정으로 카카오 연결 끊기를 건너뜀: kakao_id=%s", kakao_id)
        return

    try:
        resp = requests.post(
            KAKAO_UNLINK_URL,
            headers={"Authorization": f"KakaoAK {admin_key}"},
            data={"target_id_type": "user_id", "target_id": kakao_id},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException:
        current_app.logger.warning("Kakao unlink failed: kakao_id=%s", kakao_id, exc_info=True)
