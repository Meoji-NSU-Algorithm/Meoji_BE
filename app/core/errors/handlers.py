"""앱 전역 예외 핸들러. 모든 오류를 CommonResponse 형식의 JSON으로 변환한다."""
from flask import Flask, jsonify
from marshmallow import ValidationError
from sqlalchemy.exc import DBAPIError, TimeoutError as DatabaseTimeoutError
from werkzeug.exceptions import HTTPException, MethodNotAllowed

from app.core.errors.codes import ErrorCode
from app.core.errors.exception import BusinessException
from app.core.response import CommonResponse


def register_error_handlers(app: Flask):
    """예외 핸들러를 앱에 등록한다.

    Flask가 예외 타입에 가장 가까운 핸들러를 고르므로 등록 순서는 상관없다.
    JWT 관련 실패는 여기가 아니라 app/core/jwt_callbacks.py가 처리한다.

    - BusinessException: 의도적으로 raise한 비즈니스 실패. ErrorCode의 상태 코드로 응답한다.
    - ValidationError: Marshmallow 스키마 검증 실패. 400 COMMON_INVALID_INPUT과 필드별 errors를 응답한다.
    - HTTPException: 존재하지 않는 경로(404), 허용되지 않는 메서드(405) 등 라우팅 단계 오류.
    - DBAPIError/TimeoutError: DB 연결·풀·일시적 잠금 장애는 503, 그 외 DB 오류는 500.
    - Exception: 위에서 걸러지지 않은 모든 예외를 500으로 처리하는 최종 안전망.
    """

    @app.errorhandler(BusinessException)
    def handle_business_exception(e: BusinessException):
        """BusinessException을 e.status_code와 e.extra를 반영한 응답으로 변환한다."""
        return jsonify(CommonResponse.error(e.error_code, e.message, e.extra)), e.status_code

    @app.errorhandler(ValidationError)
    def handle_validation_error(e: ValidationError):
        """스키마 검증 실패를 400으로 변환한다. 필드별 오류(e.messages)는 errors로 내려준다."""
        # 이 핸들러가 없으면 Exception 핸들러로 떨어져 클라이언트 실수가 500으로 나간다.
        return jsonify(
            CommonResponse.error(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": e.messages})
        ), ErrorCode.COMMON_INVALID_INPUT.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(e: HTTPException):
        """라우팅 단계 HTTPException을 상태 코드별 ErrorCode로 변환한다."""
        # 404/405 외의 상태 코드는 COMMON_HTTP_ERROR에 예외 자신의 설명을 담는다.
        status_code = e.code or 500
        if isinstance(e, MethodNotAllowed):
            body = CommonResponse.error(ErrorCode.COMMON_METHOD_NOT_ALLOWED)
        elif status_code == 404:
            body = CommonResponse.error(ErrorCode.COMMON_NOT_FOUND)
        else:
            body = CommonResponse.error(ErrorCode.COMMON_HTTP_ERROR, e.description)
        response = jsonify(body)
        # 405는 Allow 헤더가 필수인데, 응답을 직접 만들면 Werkzeug가 채우던 헤더가 사라지므로 다시 채운다.
        if isinstance(e, MethodNotAllowed) and e.valid_methods:
            response.headers["Allow"] = ", ".join(e.valid_methods)
        return response, status_code

    @app.errorhandler(DBAPIError)
    @app.errorhandler(DatabaseTimeoutError)
    def handle_database_error(e):
        """DB 오류를 일시적 장애(503)와 그 외(500)로 구분해 응답한다."""
        # MySQL 연결 수 초과(1040), 잠금 대기/교착(1205/1213), 접속·단절 오류는 일시적 사용 불가로 본다.
        # 권한·SQL·무결성 오류는 500으로 남긴다.
        driver_args = getattr(getattr(e, "orig", None), "args", ())
        driver_code = driver_args[0] if driver_args else None
        error_code = (
            ErrorCode.COMMON_DB_UNAVAILABLE
            if isinstance(e, DatabaseTimeoutError)
            or driver_code in (1040, 1205, 1213, 2002, 2003, 2005, 2006, 2013)
            or getattr(e, "connection_invalidated", False)
            else ErrorCode.COMMON_INTERNAL_ERROR
        )
        # SQL·접속 정보 등 원본 오류는 로그에만 남기고 응답에는 공통 메시지만 보낸다.
        app.logger.exception(e)
        return jsonify(CommonResponse.error(error_code)), error_code.status_code

    @app.errorhandler(Exception)
    def handle_unexpected_exception(e: Exception):
        """예상하지 못한 예외를 500 COMMON_INTERNAL_ERROR로 변환한다."""
        # exception()으로 스택트레이스까지 남겨야 운영 중 원인 위치를 추적할 수 있다.
        app.logger.exception(e)

        # 실제 원인(e)은 응답에 노출하지 않는다.
        return jsonify(CommonResponse.error(ErrorCode.COMMON_INTERNAL_ERROR)), 500
