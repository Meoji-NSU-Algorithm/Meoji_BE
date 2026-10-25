# 성공 응답과 에러 응답의 JSON 포맷을 한 곳에서 통일해서 만드는 빌더.
# 라우트에서 정상 응답을 만들 때도, 전역 에러 핸들러(app/__init__.py)가 에러 응답을
# 만들 때도 반드시 이 클래스를 거치게 해서, 프론트가 항상 같은 형태의 응답을 받게 한다.
from app.core.errors.codes import ErrorCode


class CommonResponse:
    @staticmethod
    def success(data=None, message: str = "OK") -> dict:
        """정상 처리된 라우트에서 사용. 예: return jsonify(CommonResponse.success(user_dict)), 200"""
        return {"success": True, "message": message, "data": data}

    @staticmethod
    def error(error_code: ErrorCode, message: str | None = None, extra: dict | None = None) -> dict:
        """BusinessException을 JSON 바디로 변환할 때 사용.
        app/core/errors/handlers.py의 @app.errorhandler(BusinessException)에서 호출된다.

        message: BusinessException 생성 시 커스텀 메시지를 넘겼다면 그걸 우선 사용하고,
                 없으면 error_code의 기본 메시지를 사용한다.
        extra:   code/message만으로 부족한 부가 정보(예: 필드별 검증 에러)가 있을 때
                 응답 바디에 그대로 병합된다. 없으면 무시된다.
        """
        body = {
            "success": False,
            "code": error_code.code,
            "message": message or error_code.message,
        }
        if extra:
            body.update(extra)
        return body