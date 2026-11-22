"""core/images 이미지 읽기·webp 변환 테스트. 저장소에는 접속하지 않는다."""
import io

import pytest
from PIL import Image

from app.core.errors import BusinessException, ErrorCode
from werkzeug.datastructures import FileStorage

from app.core.images import convert_to_webp, read_upload


def _image_bytes(fmt="JPEG", size=(4000, 3000), mode="RGB", color="red", **save_kw):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, fmt, **save_kw)
    return out.getvalue()


def test_converts_to_webp_and_shrinks_long_side():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes(), max_side=1600)))
    assert image.format == "WEBP"
    assert max(image.size) == 1600
    assert image.size == (1600, 1200)


def test_keeps_small_image_size():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes(size=(300, 200)), max_side=1600)))
    assert image.size == (300, 200)


def test_applies_exif_rotation_and_drops_exif():
    # Orientation 6(시계 방향 90도)이면 가로 사진이 세로로 저장되어야 한다.
    exif = Image.Exif()
    exif[0x0112] = 6
    data = convert_to_webp(_image_bytes(size=(400, 200), exif=exif.tobytes()), max_side=1600)
    image = Image.open(io.BytesIO(data))
    assert image.size == (200, 400)
    assert not image.getexif()


def test_keeps_png_transparency():
    image = Image.open(io.BytesIO(convert_to_webp(_image_bytes("PNG", (50, 50), "RGBA", (255, 0, 0, 128)), max_side=1600)))
    assert image.mode == "RGBA"


@pytest.mark.parametrize("raw", [b"not an image", _image_bytes("GIF", (10, 10), "P")])
def test_rejects_non_image_and_unsupported_format(raw):
    with pytest.raises(BusinessException) as e:
        convert_to_webp(raw, max_side=1600)
    assert e.value.error_code == ErrorCode.IMAGE_INVALID


def test_accepts_mpo_phone_photo():
    """폰 카메라 JPEG(MPO)는 움직이는 이미지로 거부하지 않고 첫 프레임을 저장한다."""
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, "MPO", save_all=True, append_images=[Image.new("RGB", (40, 30), "blue")])
    image = Image.open(io.BytesIO(convert_to_webp(out.getvalue(), max_side=1600)))
    assert image.size == (40, 30) and image.getpixel((0, 0))[0] > 200


def test_rejects_too_many_pixels(monkeypatch):
    from app.core import images
    monkeypatch.setattr(images, "MAX_PIXELS", 100 * 100)
    with pytest.raises(BusinessException) as e:
        convert_to_webp(_image_bytes("PNG", (101, 100)), max_side=1600)
    assert e.value.error_code == ErrorCode.IMAGE_INVALID


def test_convert_uses_given_max_side():
    """한도는 호출하는 쪽이 정한다: 같은 사진을 512와 1600으로 줄인다."""
    raw = _image_bytes(size=(4000, 3000))
    assert Image.open(io.BytesIO(convert_to_webp(raw, max_side=512))).size == (512, 384)
    assert Image.open(io.BytesIO(convert_to_webp(raw, max_side=1600))).size == (1600, 1200)


def test_read_upload_rejects_over_limit_with_limit_in_message():
    with pytest.raises(BusinessException) as e:
        read_upload(FileStorage(io.BytesIO(b"x" * (2 * 1024 * 1024 + 1))), max_bytes=2 * 1024 * 1024)
    assert e.value.error_code == ErrorCode.IMAGE_TOO_LARGE
    assert "2MB" in e.value.message


def test_read_upload_returns_bytes_within_limit():
    assert read_upload(FileStorage(io.BytesIO(b"abc")), max_bytes=3) == b"abc"
