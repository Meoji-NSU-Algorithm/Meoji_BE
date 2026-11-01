"""users 스키마 단위 테스트."""
from app.domains.users.models import User
from app.domains.users.schemas import UserResponseSchema


def test_user_response_dump_shape():
    """정의된 필드만 노출하고 kakao_id/created_at 등은 제외한다."""
    u = User(id=1, kakao_id=99, email="a@b.com", nickname="n", profile_image="http://i")
    assert UserResponseSchema().dump(u) == {"id": 1, "email": "a@b.com", "nickname": "n", "profile_image": "http://i"}


def test_user_response_profile_image_none():
    """profile_image가 None이면 null로 직렬화된다."""
    u = User(id=1, kakao_id=99, email="a@b.com", nickname="n", profile_image=None)
    assert UserResponseSchema().dump(u)["profile_image"] is None
