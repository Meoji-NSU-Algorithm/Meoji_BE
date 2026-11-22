"""users 스키마 단위 테스트."""
import pytest

from app.domains.users.models import User
from app.domains.users.schemas import UserResponseSchema


def test_user_response_dump_shape():
    """정의된 필드만 노출하고 kakao_id/created_at 등은 제외한다."""
    u = User(id=1, kakao_id=99, email="a@b.com", nickname="n", kakao_profile_image="http://i")
    assert UserResponseSchema().dump(u) == {"id": 1, "email": "a@b.com", "nickname": "n", "profile_image": "http://i"}


def test_user_response_profile_image_none():
    """profile_image가 None이면 null로 직렬화된다."""
    u = User(id=1, kakao_id=99, email="a@b.com", nickname="n", kakao_profile_image=None)
    assert UserResponseSchema().dump(u)["profile_image"] is None


@pytest.mark.parametrize("source, expected", [
    ("kakao", "http://kakao/a"),
    ("default", None),
    ("custom", "http://img.test/profiles/x.webp"),
])
def test_profile_image_follows_source(app_ctx, monkeypatch, source, expected):
    """고른 사진(source)에 따라 profile_image 속성과 GET /me 응답이 달라진다."""
    monkeypatch.setitem(app_ctx.config, "S3_PUBLIC_URL", "http://img.test")
    u = User(id=1, kakao_id=99, email="a@b.com", nickname="n", kakao_profile_image="http://kakao/a",
             profile_image_source=source, custom_profile_image_key="profiles/x.webp")
    assert u.profile_image == expected
    assert UserResponseSchema().dump(u)["profile_image"] == expected
