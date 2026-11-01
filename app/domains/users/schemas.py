"""유저 API 응답용 marshmallow 스키마."""
from marshmallow import Schema, fields, validate

from app.core.fields import UtcDateTime

class UserResponseSchema(Schema):
    """GET /api/users/me 응답. 여기 정의한 필드만 노출되므로 kakao_id, created_at 등 내부 컬럼은 응답에서 빠진다."""
    id = fields.Integer()
    email = fields.String()
    nickname = fields.String()
    # 프로필 사진은 카카오 선택 동의 항목이라 없을 수 있다.
    profile_image = fields.String(allow_none=True)


# PyCharm이 validate.Equal 생성자를 Validator.__call__로 착각하는 오탐을 끈다.
# noinspection PyArgumentList
class ConsentRequestSchema(Schema):
    """POST /api/users/me/consents 요청. 필수 약관(terms, privacy)은 true여야만 통과한다."""
    # validate.Equal의 기본 메시지는 영어라서 error로 한국어 메시지를 지정한다.
    terms = fields.Boolean(required=True, validate=validate.Equal(True, error="서비스 이용약관에 동의해야 합니다."))
    privacy = fields.Boolean(required=True, validate=validate.Equal(True, error="개인정보 처리방침에 동의해야 합니다."))
    # 마케팅 수신은 선택 항목이라 생략하면 동의하지 않은 것으로 본다.
    marketing = fields.Boolean(load_default=False)


class ConsentResponseSchema(Schema):
    """약관 동의 조회/저장 응답. 동의 전에는 시각이 null이다."""
    terms_agreed_at = UtcDateTime(allow_none=True)
    privacy_agreed_at = UtcDateTime(allow_none=True)
    marketing_agreed = fields.Boolean()
    marketing_agreed_at = UtcDateTime(allow_none=True)
