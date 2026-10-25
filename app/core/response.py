"""성공/에러 응답의 JSON 형식을 한 곳에서 만드는 빌더. 라우트와 오류 핸들러가 모두 이 클래스를 거친다."""
from app.core.errors.codes import ErrorCode


class CommonResponse:
    """공통 응답 바디 빌더."""

    @staticmethod
    def success(data=None, message: str = "OK") -> dict:
        """성공 응답 바디를 만든다. 예: jsonify(CommonResponse.success(data)), 200"""
        return {"success": True, "message": message, "data": data}

    @staticmethod
    def error(error_code: ErrorCode, message: str | None = None, extra: dict | None = None) -> dict:
        """에러 응답 바디를 만든다.

        Args:
            error_code: code와 기본 메시지를 제공하는 ErrorCode.
            message: 지정하면 error_code의 기본 메시지 대신 사용한다.
            extra: 지정하면 응답 바디에 그대로 병합한다. (예: 필드별 검증 오류 errors)
        """
        body = {
            "success": False,
            "code": error_code.code,
            "message": message or error_code.message,
        }
        if extra:
            body.update(extra)
        return body
