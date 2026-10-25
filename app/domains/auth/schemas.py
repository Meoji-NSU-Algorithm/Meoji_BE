"""인증 API의 요청 검증/응답 직렬화용 marshmallow 스키마.

load()는 요청 body를 검증하며 실패하면 ValidationError가 발생해 400 COMMON_INVALID_INPUT이 된다.
dump()는 스키마에 정의된 필드만 골라 응답 dict를 만든다.
"""
from marshmallow import Schema, fields, validate

# PyCharm이 validate.Length 생성자를 Validator.__call__로 착각하는 오탐을 끈다.
# noinspection PyArgumentList
class KakaoLoginRequestSchema(Schema):
    """POST /api/auth/kakao 요청 body. code는 필수이며 빈 문자열은 허용하지 않는다."""
    code = fields.String(required=True, validate=validate.Length(min=1))

# noinspection PyArgumentList
class LogoutRequestSchema(Schema):
    """POST /api/auth/logout 요청 body. access 토큰과 함께 폐기할 refresh 토큰을 받는다."""
    refresh_token = fields.String(required=True, validate=validate.Length(min=1))

class TokenResponseSchema(Schema):
    """토큰 응답. 로그인과 재발급이 함께 사용한다.

    dump한 dict에 없는 키는 결과에서 빠지므로, 재발급 응답에는 is_new_user가 포함되지 않는다.
    """
    access_token = fields.String()
    refresh_token = fields.String()
    # 이번 로그인에서 회원가입이 일어났는지 여부 (프론트 온보딩 분기용)
    is_new_user = fields.Boolean()
