# 유저(users) API의 응답 형식을 정의하는 marshmallow 스키마.
# (Spring의 UserResponseDto 역할)
#
# User 모델 객체를 그대로 응답에 넣지 않고 스키마를 거치는 이유:
#   User 모델에는 kakao_id, created_at, updated_at 같은 내부용 컬럼도 있다.
#   스키마에 "내보낼 필드"만 적어 두면, 나중에 모델에 컬럼이 추가돼도
#   실수로 민감한 정보가 응답에 노출되는 일이 없다.
from marshmallow import Schema, fields

class UserResponseSchema(Schema):
    """GET /api/users/me 응답용. 사용법: UserResponseSchema().dump(user)

    예: {"id": 1, "email": "a@kakao.com", "nickname": "홍길동", "profile_image": "https://..." 또는 null}
    """
    # 여기 적은 필드만 응답에 나간다 → kakao_id, created_at 등은 자동으로 빠짐
    id = fields.Integer()        # 우리 서비스의 유저 id (PK)
    email = fields.String()      # 카카오 계정 이메일
    nickname = fields.String()   # 카카오 닉네임 (로그인할 때마다 최신 값으로 갱신됨)
    # 프로필 사진은 카카오 선택 동의 항목이라 없을 수 있다 → allow_none=True로 null 허용
    profile_image = fields.String(allow_none=True)
