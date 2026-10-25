"""환경변수(.env)에서 읽은 앱 설정 값을 모아 둔 Config 클래스."""
import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Flask app.config에 적용되는 설정. 비밀 값은 모두 .env로 주입한다."""

    # --- Kakao 로그인 (app/domains/auth/kakao_client.py에서 사용) ---

    # 카카오 앱의 REST API 키. 프론트가 카카오 로그인 페이지로 보낼 때 쓰는 client_id와 같아야 한다.
    KAKAO_CLIENT_ID = os.environ.get("KAKAO_CLIENT_ID")

    # 카카오 로그인 보안 설정에서 Client Secret을 "사용함"으로 켠 경우에만 필요하다.
    # 값이 없으면 토큰 요청에 포함하지 않는다.
    KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")

    # 카카오 콘솔에 등록한 Redirect URI. 프론트가 authorize 요청에 쓴 redirect_uri와
    # 한 글자도 달라서는 안 된다. 다르면 카카오가 KOE006을 반환하고 서버는 401 KAKAO_TOKEN_REQUEST_FAILED로 응답한다.
    KAKAO_REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI")

    # --- JWT / 외부 API / DB ---

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")

    # 한국관광공사 TourAPI 인증 키
    TOURAPI_KEY = os.environ.get("TOURAPI_KEY")

    # access token은 탈취 시 피해를 줄이기 위해 짧게, refresh token은 길게 둔다.
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=14)

    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI")
    # 풀에서 꺼낸 연결이 살아 있는지 쿼리 전에 확인해, MySQL 재시작 후 남은 끊어진 연결을 교체한다.
    # 실행 중 실패한 요청을 자동 재시도하지는 않는다.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}


# 기동 시 반드시 채워져 있어야 하는 설정 키. KAKAO_CLIENT_SECRET, TOURAPI_KEY는 선택이라 제외한다.
REQUIRED_CONFIG_KEYS = (
    "JWT_SECRET_KEY",
    "KAKAO_CLIENT_ID",
    "KAKAO_REDIRECT_URI",
    "SQLALCHEMY_DATABASE_URI",
)

# JWT 서명 키가 이보다 짧으면 무차별 대입에 약해지므로 경고한다.
JWT_SECRET_MIN_LENGTH = 32


def _is_placeholder(value: str) -> bool:
    """.env.example에서 복사한 채 남겨 둔 자리표시 값인지 판단한다."""
    upper = value.strip().upper()
    return upper == "NEED_TO_SET" or upper.startswith("YOUR_") or upper == "CHANGE"


def validate_required_config(app) -> None:
    """필수 설정이 비었거나 자리표시 값이면 기동을 중단한다.

    누락을 기동 시점에 잡지 않으면 첫 로그인 요청에서야 500으로 드러난다.
    메시지에는 키 이름과 사유만 담고 설정 값은 절대 담지 않는다.

    Raises:
        RuntimeError: 문제 있는 키를 한 번에 모두 나열한 메시지.
    """
    problems = []
    for key in REQUIRED_CONFIG_KEYS:
        value = app.config.get(key)
        if value is None or not str(value).strip():
            problems.append(f"{key}(누락)")
        elif _is_placeholder(str(value)):
            problems.append(f"{key}(자리표시 값)")
    if problems:
        raise RuntimeError(
            "필수 설정이 올바르지 않아 앱을 시작할 수 없습니다: "
            + ", ".join(problems)
            + ". .env.example을 참고해 .env를 채워주세요."
        )

    jwt_secret = str(app.config["JWT_SECRET_KEY"])
    if len(jwt_secret) < JWT_SECRET_MIN_LENGTH:
        app.logger.warning(
            "JWT_SECRET_KEY가 %d자 미만으로 짧습니다. 더 긴 무작위 값을 사용하세요.", JWT_SECRET_MIN_LENGTH
        )
