# Flask-JWT-Extended의 기본 에러 응답({"msg": "..."})을 우리 CommonResponse 포맷으로 바꾸고,
# 로그아웃된 토큰(TokenBlocklist)을 거부하는 콜백들을 등록하는 모듈.
# 데코레이터는 이 모듈이 import될 때 등록되므로 create_app()에서 반드시 import해야 한다.
#
# [콜백이란?]
#   우리가 직접 호출하는 함수가 아니라, @jwt_required()가 붙은 라우트로 요청이 올 때
#   Flask-JWT-Extended가 "특정 상황이 되면 대신 불러주는" 함수다.
#   라우트 함수 본문에 들어가기 "전에" 실행되기 때문에, 토큰에 문제가 있으면 라우트 코드는 실행되지 않는다.
#
# [@jwt_required() 요청 처리 순서와 콜백별 응답]
#   1) Authorization 헤더가 없음           → missing_token_callback  → 401 AUTH_UNAUTHORIZED
#   2) 서명 불일치/형식 오류/토큰 종류 틀림 → invalid_token_callback  → 401 AUTH_TOKEN_INVALID
#   3) 만료 시각(exp)이 지남                → expired_token_callback  → 401 AUTH_TOKEN_EXPIRED
#   4) check_if_token_revoked가 True 반환   → revoked_token_callback  → 401 AUTH_TOKEN_REVOKED
#   5) 모두 통과                           → 라우트 함수 실행
#
# [파라미터 이름 앞의 _ 는?]
#   라이브러리가 콜백을 호출할 때 정해진 개수의 인자를 "위치 순서대로" 넘긴다.
#   우리가 쓰지 않는 인자라도 파라미터를 지우면 호출 시 TypeError → 500이 난다.
#   그래서 지우지 않고, "일부러 안 쓰는 인자"라는 파이썬 관례대로 이름 앞에 _를 붙였다.
from flask import jsonify

from app.core.extensions import jwt, db
from app.domains.auth.models import TokenBlocklist
from app.core.response import CommonResponse
from app.core.errors import ErrorCode


def _error(error_code: ErrorCode):
    """ErrorCode를 (JSON 응답, 상태코드) 튜플로 만든다. 아래 콜백들이 공통으로 사용.
    전역 핸들러(app/__init__.py)가 BusinessException을 응답으로 바꾸는 것과 같은 포맷이다.
    예: ({"success": false, "code": "AUTH_TOKEN_EXPIRED", "message": "토큰이 만료되었습니다."}, 401)
    """
    return jsonify(CommonResponse.error(error_code)), error_code.status_code


@jwt.token_in_blocklist_loader
def check_if_token_revoked(_jwt_header, jwt_payload) -> bool:
    """@jwt_required가 붙은 모든 요청마다 호출된다. True를 반환하면 revoked로 처리된다.

    로그아웃(token_service.revoke_tokens)이나 refresh 재발급(token_service.rotate_refresh_token) 때
    폐기된 토큰의 jti가 TokenBlocklist 테이블에 저장되어 있다.
    여기서 그 테이블에 현재 토큰의 jti가 있는지 확인해서, 있으면 요청을 거부한다.
    """
    jti = jwt_payload["jti"]  # 토큰마다 붙는 고유 ID
    # SELECT id FROM token_blocklist WHERE jti = ? → 있으면 id, 없으면 None
    # jti 컬럼에 인덱스가 걸려 있어서 매 요청마다 조회해도 빠르다.
    return db.session.query(TokenBlocklist.id).filter_by(jti=jti).scalar() is not None


@jwt.unauthorized_loader
def missing_token_callback(_reason):
    # Authorization 헤더 자체가 없음 (로그인하지 않은 상태로 보호된 API 호출)
    # _reason: 라이브러리가 넘겨주는 영문 실패 사유 문자열 (응답에 노출하지 않으므로 사용 안 함)
    return _error(ErrorCode.AUTH_UNAUTHORIZED)


@jwt.invalid_token_loader
def invalid_token_callback(_reason):
    # 서명 불일치(위조), 형식 오류, access/refresh 종류가 틀린 경우
    # (예: /refresh에 access 토큰을 넣음, 로그아웃 body에 깨진 refresh 토큰을 넣음)
    return _error(ErrorCode.AUTH_TOKEN_INVALID)


@jwt.expired_token_loader
def expired_token_callback(_jwt_header, _jwt_payload):
    # exp 지남 → 프론트는 refresh 시도
    # (refresh 토큰까지 만료된 경우에도 이 응답이 나가며, 그때는 다시 카카오 로그인해야 한다)
    return _error(ErrorCode.AUTH_TOKEN_EXPIRED)


@jwt.revoked_token_loader
def revoked_token_callback(_jwt_header, _jwt_payload):
    # check_if_token_revoked가 True를 반환한 경우
    # = 로그아웃된 토큰이거나, 이미 한 번 사용한 refresh 토큰 → 프론트는 로그인 화면으로
    return _error(ErrorCode.AUTH_TOKEN_REVOKED)
