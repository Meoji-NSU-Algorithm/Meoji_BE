"""리뷰 이미지 key 형식 테스트."""
import pytest

from app.domains.reviews.images import KEY_PATTERN


@pytest.mark.parametrize("key, ok", [
    ("reviews/" + "a" * 32 + ".webp", True),
    ("reviews/" + "a" * 32 + ".jpg", False),
    ("https://evil.example/x.webp", False),
    ("reviews/../" + "a" * 29 + ".webp", False),
])
def test_key_pattern(key, ok):
    assert bool(KEY_PATTERN.match(key)) is ok
