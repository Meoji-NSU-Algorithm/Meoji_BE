"""유저 API 응답용 marshmallow 스키마."""
from marshmallow import Schema, fields

class UserResponseSchema(Schema):
    """GET /api/users/me 응답. 여기 정의한 필드만 노출되므로 kakao_id, created_at 등 내부 컬럼은 응답에서 빠진다."""
    id = fields.Integer()
    email = fields.String()
    nickname = fields.String()
    # 프로필 사진은 카카오 선택 동의 항목이라 없을 수 있다.
    profile_image = fields.String(allow_none=True)
