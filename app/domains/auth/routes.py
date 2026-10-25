# 인증(auth) 관련 API 라우트 모음. (Spring의 AuthController 역할)
#
# [라우트(컨트롤러)의 책임은 딱 3가지만]
#   1) 요청 값 검증   : 스키마(app/domains/auth/schemas.py)의 load()로 body를 검사
#   2) 서비스 호출    : 실제 로직은 전부 app/domains/auth/service.py에 맡긴다
#   3) 응답 만들기    : CommonResponse.success()로 공통 포맷에 담아 반환
#   → 비즈니스 로직, DB 접근, try/except는 여기에 쓰지 않는다.
#
# [try/except가 없는 이유]
#   여기서 발생하는 예외는 전부 전역 핸들러가 공통 JSON 포맷으로 바꿔서 응답한다.
#   - 스키마 검증 실패(ValidationError)   → app/__init__.py 핸들러 → 400 COMMON_INVALID_INPUT
#   - 서비스의 BusinessException          → app/__init__.py 핸들러 → ErrorCode에 정의된 상태코드
#   - JWT 관련 실패(없음/만료/위조/로그아웃) → app/core/jwt_callbacks.py 콜백 → 401 AUTH_TOKEN_*
#   - 그 외 예상 못한 예외                 → app/__init__.py 핸들러 → 500 COMMON_INTERNAL_ERROR
#
# [프론트 기준 전체 흐름]
#   1) 카카오 로그인 → 받은 code로 POST /api/auth/kakao → access_token, refresh_token 받음
#   2) 이후 모든 API 요청 헤더에  Authorization: Bearer <access_token>
#   3) access_token 만료(AUTH_TOKEN_EXPIRED) → POST /api/auth/refresh 로 새 토큰 쌍 받기
#   4) 로그아웃 → POST /api/auth/logout
from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt

from app.core.response import CommonResponse
from app.domains.auth.schemas import KakaoLoginRequestSchema, LogoutRequestSchema, TokenResponseSchema
from app.domains.auth import service as auth_service

# url_prefix="/auth" 인 이유: 부모 Blueprint(app/core/api.py의 api_bp)가 "/api"를 이미 붙여준다.
# 그래서 이 파일의 라우트 최종 경로는 /api/auth/... 가 된다.
auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

@auth_bp.post("/kakao")
def kakao_login():
    """카카오 로그인 (처음 온 사용자면 회원가입까지 자동 처리)

    POST /api/auth/kakao
    인증 헤더: 필요 없음 (아직 로그인 전이므로)
    요청 body: {"code": "카카오가 redirect_uri로 넘겨준 인가 코드"}

    성공 응답 (200):
        {
          "success": true, "message": "OK",
          "data": {
            "access_token": "eyJ...",   ← 이후 API 호출 시 Authorization 헤더에 사용 (1시간)
            "refresh_token": "eyJ...",  ← access 만료 시 재발급에 사용 (14일), 안전하게 보관
            "is_new_user": true         ← true면 이번에 회원가입된 유저 → 프론트에서 온보딩 화면 등으로 분기
          }
        }

    실패 응답:
        400 COMMON_INVALID_INPUT       : body에 code가 없거나 빈 문자열
        401 KAKAO_TOKEN_REQUEST_FAILED : code가 만료(약 10분)/재사용(일회용)/redirect_uri 불일치
                                         → 프론트는 카카오 로그인을 처음부터 다시 시작
    """
    # request.get_json(silent=True):
    #   body가 JSON이 아니거나 비어 있으면 에러를 던지지 않고 None을 반환한다.
    #   silent=True가 없으면 Flask가 자체적으로 400을 던져서 우리 공통 응답 포맷을 벗어난다.
    # `or {}`:
    #   None 대신 빈 dict를 넘겨서, 스키마가 "code 필드가 필수입니다" 라는
    #   필드 단위 에러(400 COMMON_INVALID_INPUT)로 깔끔하게 응답하게 만든다.
    # .load():
    #   검증에 통과하면 검증된 dict를 반환하고, 실패하면 ValidationError를 던진다.
    body = KakaoLoginRequestSchema().load(request.get_json(silent=True) or {})

    # 카카오 토큰 교환 → 카카오 사용자 정보 조회 → 유저 조회/생성 → 우리 JWT 발급까지
    # 전부 서비스가 처리하고, 결과로 {"access_token", "refresh_token", "is_new_user"} dict를 돌려준다.
    result = auth_service.login_with_kakao(body["code"])

    # .dump(): 파이썬 dict/객체를 스키마에 정의된 필드만 골라 응답용 dict로 변환한다.
    return jsonify(CommonResponse.success(TokenResponseSchema().dump(result))), 200

@auth_bp.post("/refresh")
# refresh=True: access 토큰이 아니라 "refresh 토큰"만 받겠다는 뜻.
#   access 토큰을 넣으면 → 401 AUTH_TOKEN_INVALID
#   이 데코레이터가 서명 검증, 만료 확인, 블록리스트(로그아웃/이미 사용됨) 확인까지 다 해준다.
@jwt_required(refresh=True)
def refresh_token():
    """access 토큰 재발급 (Refresh Token Rotation)

    POST /api/auth/refresh
    인증 헤더: Authorization: Bearer <refresh_token>   ← access가 아니라 refresh!
    요청 body: 없음

    성공 응답 (200):
        {"success": true, "message": "OK",
         "data": {"access_token": "새 access", "refresh_token": "새 refresh"}}
        ※ refresh_token도 새로 발급된다. 프론트는 반드시 저장된 refresh_token을 새 값으로 교체해야 한다.
          방금 사용한 refresh_token은 폐기되어 다시 쓰면 401 AUTH_TOKEN_REVOKED가 난다.

    실패 응답:
        401 AUTH_UNAUTHORIZED  : Authorization 헤더 없음
        401 AUTH_TOKEN_INVALID : 위조/형식 오류, 또는 refresh 자리에 access 토큰을 넣음
        401 AUTH_TOKEN_EXPIRED : refresh 토큰도 만료(14일) → 프론트는 다시 카카오 로그인
        401 AUTH_TOKEN_REVOKED : 이미 사용했거나 로그아웃된 refresh 토큰
        404 USER_NOT_FOUND     : 토큰은 유효하지만 유저가 탈퇴 등으로 없음
    """
    # get_jwt(): 현재 요청 헤더에 담긴 토큰의 payload(내용물) 전체를 dict로 꺼낸다.
    #   예: {"sub": "1", "jti": "고유ID", "type": "refresh", "exp": 만료시각, ...}
    #   서비스에는 Flask 요청 객체가 아니라 이 "값"만 넘긴다 → 서비스가 Flask 요청에 의존하지 않게.
    tokens = auth_service.refresh(get_jwt())

    # TokenResponseSchema에 is_new_user 필드도 있지만, tokens dict에 그 키가 없으므로
    # dump 결과에서 자동으로 빠진다. (로그인 응답과 같은 스키마를 재사용하기 위함)
    return jsonify(CommonResponse.success(TokenResponseSchema().dump(tokens))), 200

@auth_bp.post("/logout")
# 인자 없는 @jwt_required(): access 토큰만 받는다. (refresh 토큰을 넣으면 401 AUTH_TOKEN_INVALID)
@jwt_required()
def logout():
    """로그아웃 (access 토큰 + refresh 토큰 둘 다 폐기)

    POST /api/auth/logout
    인증 헤더: Authorization: Bearer <access_token>
    요청 body: {"refresh_token": "보관 중인 refresh 토큰"}

    [왜 refresh 토큰까지 body로 받나?]
        JWT는 서버가 강제로 만료시킬 수 없어서, 로그아웃은 "블록리스트(TokenBlocklist 테이블)에
        등록해서 앞으로 거부하는 방식"으로 구현한다. access만 등록하면 남아 있는 refresh로
        새 access를 발급받을 수 있어서 로그아웃이 무의미해진다. 그래서 둘 다 등록한다.

    성공 응답 (200):
        {"success": true, "message": "로그아웃 되었습니다.", "data": null}
        → 프론트는 저장해 둔 access/refresh 토큰을 모두 삭제한다.

    실패 응답:
        400 COMMON_INVALID_INPUT : body에 refresh_token이 없음
        401 AUTH_UNAUTHORIZED    : Authorization 헤더 없음
        401 AUTH_TOKEN_INVALID   : 토큰 위조, 또는 body의 refresh_token이 본인 것이 아님
        401 AUTH_TOKEN_EXPIRED   : access 토큰 만료 → refresh 후 다시 로그아웃 요청
        401 AUTH_TOKEN_REVOKED   : 이미 로그아웃된 access 토큰
    """
    # kakao_login과 같은 이유로 silent=True + `or {}` 사용 (위 주석 참고)
    body = LogoutRequestSchema().load(request.get_json(silent=True) or {})

    # get_jwt()는 헤더의 access 토큰 payload. body의 refresh 토큰 문자열과 함께 서비스에 넘긴다.
    auth_service.logout(get_jwt(), body["refresh_token"])

    # 돌려줄 데이터가 없으므로 data 없이 message만 담는다. (data는 기본값 None → null)
    return jsonify(CommonResponse.success(message="로그아웃 되었습니다.")), 200
