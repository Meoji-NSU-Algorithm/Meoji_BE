"""업로드 이미지를 읽고 webp로 변환한다. 용량·크기 한도는 호출하는 도메인이 정한다.

업로드한 원본은 저장하지 않고, 긴 변을 줄여 webp로 다시 인코딩한 결과만 저장한다.
다시 인코딩하면 EXIF(촬영 위치 등)가 빠지고 이미지가 아닌 파일은 여기서 걸러진다.
"""

import io

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import BusinessException, ErrorCode

WEBP_QUALITY = 80

# 압축은 작지만 풀면 거대한 이미지(픽셀 폭탄)를 막는다. 보안 장치라 도메인이 바꾸지 않는다.
# Pillow의 MAX_IMAGE_PIXELS는 한도의 2배까지 경고만 내므로 헤더 크기로 직접 검사한다.
MAX_PIXELS = 40_000_000

# 업로드를 받는 형식. 움직이는 GIF는 지원하지 않는다.
_ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")


def read_upload(file_storage, *, max_bytes: int) -> bytes:
    """업로드 파일을 바이트로 읽는다.

    Raises:
        BusinessException: max_bytes를 넘으면 IMAGE_TOO_LARGE.
    """
    # 한도보다 1바이트 더 읽어, 넘는 파일을 끝까지 메모리에 올리지 않고 판단한다.
    raw = file_storage.stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise BusinessException(
            ErrorCode.IMAGE_TOO_LARGE, f"이미지는 한 장에 {max_bytes // (1024 * 1024)}MB까지 올릴 수 있습니다."
        )
    return raw


def convert_to_webp(raw: bytes, *, max_side: int) -> bytes:
    """이미지 바이트를 회전 보정하고 긴 변을 max_side 이하로 줄인 webp 바이트로 바꾼다.

    Raises:
        BusinessException: 이미지가 아니거나 지원하지 않는 형식이면 IMAGE_INVALID.
    """
    try:
        # verify()는 파일 구조만 검사하고 이미지를 못 쓰게 만들므로 다시 연다.
        Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS).verify()
        image = Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS)
        if image.width * image.height > MAX_PIXELS:
            raise BusinessException(ErrorCode.IMAGE_INVALID, "이미지 해상도가 너무 큽니다.")
        # 폰 카메라 JPEG는 보조 프레임이 붙은 MPO로 열린다. 움직이는 이미지가 아니므로 첫 프레임만 쓴다.
        if image.format != "MPO" and getattr(image, "is_animated", False):
            raise BusinessException(ErrorCode.IMAGE_INVALID, "움직이는 이미지는 올릴 수 없습니다.")

        # JPEG는 디코딩할 때 1/2~1/8로 줄여 읽어 원본 크기만큼 메모리를 쓰지 않는다. 다른 형식은 무시된다.
        image.draft("RGB", (max_side, max_side))

        # EXIF 회전 정보를 픽셀에 반영한다. 다시 인코딩하면 EXIF가 빠져 폰 사진이 눕기 때문이다.
        image = ImageOps.exif_transpose(image)
        # webp는 RGB/RGBA만 저장하므로 CMYK·팔레트(P) 등은 변환한다. 투명도(RGBA)는 유지한다.
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.thumbnail((max_side, max_side))

        out = io.BytesIO()
        image.save(out, "WEBP", quality=WEBP_QUALITY)
        return out.getvalue()
    except BusinessException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise BusinessException(ErrorCode.IMAGE_INVALID) from error
