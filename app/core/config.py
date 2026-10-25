import os                      # .env/환경변수 값을 읽어오기 위한 표준 라이브러리
from datetime import timedelta # JWT 토큰 만료 기간을 지정하기 위해 사용

from dotenv import load_dotenv # .env 파일을 파싱해서 os.environ에 로드해주는 라이브러리

# .env 파일 내용을 읽어서 os.environ에 등록하는 함수
load_dotenv()


class Config:

    # ==============================
    # KAKAO API (app/domains/auth/kakao_client.py에서 사용)
    # 값은 모두 카카오 디벨로퍼스(developers.kakao.com) → 내 애플리케이션에서 확인/설정한다.
    # ==============================

    # 카카오 앱의 "REST API 키". [앱 키] 메뉴에서 확인.
    # 프론트가 카카오 로그인 페이지로 보낼 때 쓰는 client_id와 같은 값이어야 한다.
    KAKAO_CLIENT_ID = os.environ.get("KAKAO_CLIENT_ID")

    # 보안 강화용 비밀키. [카카오 로그인] → [보안] 메뉴에서 "사용함"으로 켰을 때만 필요하다.
    # 사용 안 함이면 .env에서 비워둬도 된다. (값이 없으면 토큰 요청에 포함하지 않음)
    # 외부에 노출되면 안 되므로 절대 프론트 코드나 git에 올리지 않는다.
    KAKAO_CLIENT_SECRET = os.environ.get("KAKAO_CLIENT_SECRET")

    # 카카오 로그인 후 code를 받을 주소. [카카오 로그인] → [Redirect URI]에 등록된 값이어야 하고,
    # 프론트가 카카오 로그인 페이지로 보낼 때 쓴 redirect_uri와 한 글자도 달라선 안 된다.
    # (다르면 카카오가 KOE006 에러를 주고, 우리 서버는 401 KAKAO_TOKEN_REQUEST_FAILED로 응답)
    # 예: 로컬 개발 시 http://localhost:3000/oauth/kakao/callback (프론트 주소)
    KAKAO_REDIRECT_URI = os.environ.get("KAKAO_REDIRECT_URI")

    # JWT 서명/검증에 쓰는 비밀키. .env의 JWT_SECRET_KEY 값을 그대로 사용
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY")

    # 한국관광공사 API 키. .env의 TOURAPI_KEY 값을 그대로 사용
    TOURAPI_KEY = os.environ.get("TOURAPI_KEY")

    # access token 유효기간 (짧게 유지, 만료되면 refresh token으로 재발급)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)

    # refresh token 유효기간 (access token보다 길게)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=14)

    # DB 접속 URL. .env의 SQLALCHEMY_DATABASE_URI 값을 그대로 사용
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI")
    # 풀에서 꺼낸 연결이 살아 있는지 확인한다. MySQL 재시작 후 남은 오래된 연결은
    # 쿼리 실행 전에 교체한다. 실행 중 실패한 요청을 자동 재실행하는 옵션은 아니다.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
