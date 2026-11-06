"""리뷰 이미지 webp 변환 테스트. 저장소에는 접속하지 않는다."""
import io

import pytest
from PIL import Image

from app.core.errors import BusinessException, ErrorCode
from app.domains.reviews.images import KEY_PATTERN, MAX_SIDE, convert_to_webp


def _image_bytes(fmt="JPEG", size=(4000, 3000), mode="RGB", color="red", **save_kw):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt, **save_kw)
    return out.getvalue()


def test_converts_to_webp_and_shrinks_long_side():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes())))
    assert image.format == "WEBP"
    assert max(image.size) == MAX_SIDE
    assert image.size == (1600, 1200)


def test_keeps_small_image_size():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes(size=(300, 200)))))
    assert image.size == (300, 200)


def test_applies_exif_rotation_and_drops_exif():
    # Orientation 6(시계 방향 90도)이면 가로 사진이 세로로 저장되어야 한다.
    exif = Image.Exif()
    exif[0x0112] = 6
    data = convert_to_webp(_image_bytes(size=(400, 200), exif=exif.tobytes()))
    image = Image.open(io.BytesIO(data))
    assert image.size == (200, 400)
    assert not image.getexif()


def test_keeps_png_transparency():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes("PNG", (50, 50), "RGBA", (255, 0, 0, 128)))))
    assert image.mode == "RGBA"


@pytest.mark.parametrize("raw", [b"not an image", _image_bytes("GIF", (10, 10), "P")])
def test_rejects_non_image_and_unsupported_format(raw):
    with pytest.raises(BusinessException) as e:
        convert_to_webp(raw)
    assert e.value.error_code == ErrorCode.REVIEW_IMAGE_INVALID


@pytest.mark.parametrize("key, ok", [
    ("reviews/" + "a" * 32 + ".webp", True),
    ("reviews/" + "a" * 32 + ".jpg", False),
    ("https://evil.example/x.webp", False),
    ("reviews/../" + "a" * 29 + ".webp", False),
])
def test_key_pattern(key, ok):
    assert bool(KEY_PATTERN.match(key)) is ok


def test_accepts_mpo_phone_photo():
    """폰 카메라 JPEG(MPO, 보조 프레임 포함)는 움직이는 이미지가 아니다. 첫 프레임만 저장한다."""
    out = io.BytesIO()
    Image.new("RGB", (400, 300), "red").save(out, "MPO", save_all=True, append_images=[Image.new("RGB", (400, 300), "blue")])
    image = Image.open(io.BytesIO(convert_to_webp(out.getvalue())))
    assert image.format == "WEBP" and image.size == (400, 300)
    assert image.getpixel((0, 0))[0] > 200  # 빨간 첫 프레임


def test_rejects_animated_webp():
    out = io.BytesIO()
    Image.new("RGB", (20, 20), "red").save(out, "WEBP", save_all=True, append_images=[Image.new("RGB", (20, 20), "blue")])
    with pytest.raises(BusinessException) as e:
        convert_to_webp(out.getvalue())
    assert e.value.error_code == ErrorCode.REVIEW_IMAGE_INVALID


def test_rejects_too_many_pixels(monkeypatch):
    """픽셀 수 한도를 헤더 크기로 직접 검사한다(Pillow 경고 구간에 기대지 않는다)."""
    from app.domains.reviews import images
    monkeypatch.setattr(images, "MAX_PIXELS", 100 * 100)
    with pytest.raises(BusinessException) as e:
        convert_to_webp(_image_bytes("PNG", (101, 100)))
    assert e.value.error_code == ErrorCode.REVIEW_IMAGE_INVALID


def test_large_jpeg_keeps_orientation_and_size_with_draft():
    """축소 디코딩(draft)을 써도 회전 보정과 최종 크기는 그대로다."""
    exif = Image.Exif()
    exif[0x0112] = 6
    data = convert_to_webp(_image_bytes(size=(4000, 3000), exif=exif.tobytes()))
    assert Image.open(io.BytesIO(data)).size == (1200, 1600)
