# app/core/errors 패키지의 유일한 예외 클래스.
# 반드시 Exception을 상속해야 한다 — app/core/errors/handlers.py의 @app.errorhandler(BusinessException)이
# 이 클래스를 잡으려면 Exception의 서브클래스여야 하기 때문 (ErrorCode를 상속하면 안 됨).
from app.core.errors.codes import ErrorCode


class BusinessException(Exception):
    """비즈니스 로직에서 발생하는 모든 예외의 단일 클래스.

    AuthException, ValidationException 처럼 상황(도메인)별로 예외 클래스를 따로 만들면
    카카오 로그인/JWT처럼 실패 케이스가 계속 늘어날 때마다 클래스도 같이 늘어나야 한다.
    그래서 클래스는 이거 하나로 고정하고, 실제 "무엇이 잘못됐는지"는 ErrorCode로만 구분한다.
    새 실패 케이스가 생기면 codes.py의 ErrorCode에 멤버 하나만 추가하면 되고,
    이 파일은 건드릴 필요가 없다.

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
        self.error_code = error_code
        # message를 안 넘기면 ErrorCode에 정의된 기본 메시지를 그대로 쓰고,
        # 넘기면 그 요청/상황에 맞는 메시지로 덮어쓴다.
        self.message = message or error_code.message
        # status_code는 클래스가 아니라 ErrorCode 쪽에 들어있다 (codes.py 참고).
        # 그래서 "401짜리 예외 클래스", "404짜리 예외 클래스"를 따로 만들 필요가 없다.
        self.status_code = error_code.status_code
        # code/message만으로 표현이 안 되는 부가 정보(예: 필드별 검증 에러)를 담는 자리.
        # 대부분의 경우엔 안 쓰고, 꼭 필요한 특수 케이스에서만 채운다.
        self.extra = extra or {}
        super().__init__(self.message)
