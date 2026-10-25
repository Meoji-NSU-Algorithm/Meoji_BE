from flask import Flask, jsonify
from marshmallow import ValidationError  # 스키마 load() 검증 실패 시 발생하는 예외 (아래 핸들러에서 400으로 변환)
from sqlalchemy.exc import DBAPIError, TimeoutError as DatabaseTimeoutError
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from app.core.errors.codes import ErrorCode
from app.core.errors.exception import BusinessException
from app.core.response import CommonResponse


def register_error_handlers(app: Flask):
    """Spring Boot의 @RestControllerAdvice + @ExceptionHandler 역할.
    앱 전체에서 발생하는 예외를 라우트마다 try/except로 잡지 않고 여기 한 곳에서
    전부 공통 JSON 포맷으로 응답한다. Flask는 raise된 예외의 타입과 가장 가까운
    @app.errorhandler를 자동으로 찾아 호출해주기 때문에, 등록 순서는 상관없다.

    아래 핸들러들은 "얼마나 예상된 예외인가" 순으로 안전망이 겹쳐 있다.
    1) BusinessException : 우리가 의도적으로 raise하는 비즈니스 실패 케이스.
       새 실패 케이스가 생겨도 이 함수나 새 예외 클래스를 추가할 필요 없이
       app/core/errors/codes.py의 ErrorCode에 멤버 하나만 추가하고
       raise BusinessException(ErrorCode.그_멤버)만 하면 된다.
    2) ValidationError : Marshmallow 스키마의 요청값 검증 실패.
       400 COMMON_INVALID_INPUT과 필드별 errors를 응답한다.
    ※ JWT 관련 실패(토큰 없음/만료/위조/로그아웃됨)는 여기가 아니라
       app/core/jwt_callbacks.py의 콜백들이 처리한다.
    3) HTTPException : 존재하지 않는 라우트(404), 잘못된 HTTP 메서드(405) 등
       Flask/Werkzeug가 라우팅 단계에서 자체적으로 던지는 예외.
    4) DBAPIError/TimeoutError : DB 연결·풀·일시적 잠금 장애는 503으로 구분한다.
       쿼리·권한 등 다른 DB 실행 오류는 기존 내부 오류(500)로 응답한다.
    5) Exception : 위 경우로 못 거른, 코드 버그나 외부 API 실패 등
       예상 못한 모든 예외를 잡는 최종 안전망. 이게 없으면 이런 예외는
       그대로 500으로 터지면서 우리 공통 응답 포맷을 벗어난다.
    """

    @app.errorhandler(BusinessException)
    def handle_business_exception(e: BusinessException):
        # e.status_code / e.error_code 둘 다 BusinessException이 아니라 e.error_code(ErrorCode)에서
        # 정해진 값이다 (app/core/errors/exception.py, app/core/errors/codes.py 참고).
        return jsonify(CommonResponse.error(e.error_code, e.message, e.extra)), e.status_code

    @app.errorhandler(ValidationError)
    def handle_validation_error(e: ValidationError):
        # marshmallow 스키마의 load()가 실패하면(필수값 누락, 빈 문자열 등) 여기로 온다.
        # 이 핸들러가 없으면 아래 Exception 핸들러로 떨어져서 클라이언트 실수인데도 500이 나간다.
        # e.messages에 필드별 에러가 dict로 들어 있어서 extra로 그대로 내려준다.
        # 예: {"success": false, "code": "COMMON_INVALID_INPUT", "message": "요청 값이 올바르지 않습니다.",
        #      "errors": {"code": ["Missing data for required field."]}}
        return jsonify(
            CommonResponse.error(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": e.messages})
        ), ErrorCode.COMMON_INVALID_INPUT.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        # 404, 405 같은 라우팅 단계 오류. 상태 코드별 ErrorCode로 다른 오류와 같은 형식으로 만든다.
        # 매핑되지 않은 상태 코드는 COMMON_HTTP_ERROR에 예외 자신의 설명과 상태 코드를 쓴다.
        status_code = e.code or 500
        if isinstance(e, MethodNotAllowed):
            body = CommonResponse.error(ErrorCode.COMMON_METHOD_NOT_ALLOWED)
        elif status_code == 404:
            body = CommonResponse.error(ErrorCode.COMMON_NOT_FOUND)
        else:
            body = CommonResponse.error(ErrorCode.COMMON_HTTP_ERROR, e.description)
        response = jsonify(body)
        # 405는 RFC상 Allow 헤더가 필수다. Werkzeug가 만들어 주던 헤더가 직접 응답을 만들면서
        # 사라지므로, 허용 메서드 목록(e.valid_methods)으로 다시 채운다.
        if isinstance(e, MethodNotAllowed) and e.valid_methods:
            response.headers["Allow"] = ", ".join(e.valid_methods)
        return response, status_code

    @app.errorhandler(DBAPIError)
    @app.errorhandler(DatabaseTimeoutError)
    def handle_database_error(e):
        # MySQL 연결 수 초과(1040), 잠금 대기/교착(1205/1213), 접속·단절 오류를
        # 일시적 사용 불가로 분류한다. 계정 권한·SQL·무결성 오류는 500으로 남긴다.
        driver_args = getattr(getattr(e, "orig", None), "args", ())
        driver_code = driver_args[0] if driver_args else None
        error_code = (
            ErrorCode.COMMON_DB_UNAVAILABLE
            if isinstance(e, DatabaseTimeoutError)
            or driver_code in (1040, 1205, 1213, 2002, 2003, 2005, 2006, 2013)
            or getattr(e, "connection_invalidated", False)
            else ErrorCode.COMMON_INTERNAL_ERROR
        )
        # SQL·접속 정보·원본 오류는 로그에서 확인하고 응답에는 공통 메시지만 보낸다.
        app.logger.exception(e)
        return jsonify(CommonResponse.error(error_code)), error_code.status_code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        # BusinessException도, HTTPException도 아닌 그 외 모든 예외(코드 버그,
        # DB/외부 API 호출 중 발생한 미처리 예외 등)를 여기서 최종적으로 잡는다.
        # error()가 아니라 exception()을 써야 스택트레이스까지 로그에 남아서
        # 운영 중 500 에러의 원인을 코드 위치까지 추적할 수 있다.
        app.logger.exception(e)

        # 실제 원인(e)은 로그로만 남기고, 응답에는 노출하지 않는다.
        # 클라이언트에는 항상 동일한 일반 메시지(COMMON_INTERNAL_ERROR)만 내려준다.
        return jsonify(CommonResponse.error(ErrorCode.COMMON_INTERNAL_ERROR)), 500
