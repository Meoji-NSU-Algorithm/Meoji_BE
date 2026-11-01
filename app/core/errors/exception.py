"""비즈니스 로직용 단일 예외 클래스 BusinessException."""
from app.core.errors.codes import ErrorCode


class BusinessException(Exception):
    """비즈니스 로직에서 발생하는 모든 예외의 단일 클래스.

    상황별로 예외 클래스를 늘리지 않고, 무엇이 잘못됐는지는 ErrorCode로만 구분한다.
    새 실패 케이스는 ErrorCode에 멤버를 추가하면 되고 이 파일은 바꿀 필요가 없다.
    Exception을 상속해야 handlers.py의 @app.errorhandler(BusinessException)이 잡을 수 있다.

    사용 예:
        raise BusinessException(ErrorCode.AUTH_TOKEN_EXPIRED)
        raise BusinessException(ErrorCode.AUTH_TOKEN_EXPIRED, "세션이 만료되었습니다")
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"email": ["형식이 올바르지 않습니다"]}})
    """

    def __init__(
            self,
            error_code: ErrorCode,
            message: str | None = None,
            extra: dict | None = None,
    ):
        """
        Args:
            error_code: 오류 종류. 상태 코드와 기본 메시지를 결정한다.
            message: 지정하면 기본 메시지를 덮어쓴다.
            extra: code/message로 표현할 수 없는 부가 정보. 응답 바디에 병합된다.
        """
        self.error_code = error_code
        self.message = message or error_code.message
        self.status_code = error_code.status_code
        self.extra = extra or {}
        super().__init__(self.message)
