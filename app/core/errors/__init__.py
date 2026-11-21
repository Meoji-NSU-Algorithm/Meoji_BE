"""오류 패키지. ErrorCode와 BusinessException을 `from app.core.errors import ...`로 쓰도록 노출한다."""
from app.core.errors.codes import ErrorCode
from app.core.errors.exception import BusinessException

__all__ = ["ErrorCode", "BusinessException"]
