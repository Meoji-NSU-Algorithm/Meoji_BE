"""리뷰 이미지 변환과 저장소 key 발급을 담당한다. 저장소 통신은 storage_client.py가 맡는다.

업로드한 원본은 저장하지 않고, 긴 변을 줄여 webp로 다시 인코딩한 결과만 저장한다.
다시 인코딩하면 EXIF(촬영 위치 등)가 빠지고 이미지가 아닌 파일은 여기서 걸러진다.
DB에는 저장소 키(`reviews/<uuid>.webp`)만 저장하고 URL은 응답 시점에 만든다.
스키마(schemas.py → events/schemas.py)가 이 모듈의 상수를 import하므로 저장소 모듈(boto3)은 import하지 않는다.
"""

import io
import re
import uuid

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import BusinessException, ErrorCode

# 리뷰 한 건에 붙일 수 있는 최대 장수
MAX_REVIEW_IMAGES = 5

# 변환 전 원본 한 장의 최대 크기. 변환하려면 메모리에 올려야 하므로 원본 기준으로 막는다.
# 요청 본문 전체는 config.MAX_CONTENT_LENGTH가 먼저 막는다.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 원본의 최대 픽셀 수. 압축은 작지만 풀면 거대한 이미지(픽셀 폭탄)를 막는다.
# Pillow의 MAX_IMAGE_PIXELS는 한도의 2배까지 경고만 내므로 쓰지 않고, 헤더의 크기로 직접 검사한다.
MAX_PIXELS = 40_000_000

# 저장할 이미지의 긴 변(px). 폰 사진(4000px 안팎)을 이 크기로 줄이는 것이 용량 절감의 대부분이다.
MAX_SIDE = 1600

WEBP_QUALITY = 80

# 업로드를 받는 형식. 움직이는 GIF는 지원하지 않는다.
# 폰 카메라 JPEG는 JPEG로 열려도 보조 이미지가 붙은 MPO 객체가 된다(convert_to_webp의 is_animated 검사 참고).
_ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")

# 이 서버가 만든 키만 리뷰에 연결할 수 있게 형식을 고정한다. 외부 URL이나 다른 경로를 막는다.
KEY_PATTERN = re.compile(r"^reviews/[0-9a-f]{32}\.webp$")


def convert_to_webp(raw: bytes) -> bytes:
    """이미지 바이트를 회전 보정·리사이즈한 webp 바이트로 바꾼다.

    Raises:
        BusinessException: 이미지가 아니거나 지원하지 않는 형식, 픽셀 수 초과면 REVIEW_IMAGE_INVALID.
    """
    try:
        # verify()는 파일 구조만 검사하고 이미지를 못 쓰게 만들므로 다시 연다.
        Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS).verify()
        image = Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS)
        # open은 헤더만 읽으므로 픽셀을 풀기 전에 크기로 막을 수 있다.
        if image.width * image.height > MAX_PIXELS:
            raise BusinessException(ErrorCode.REVIEW_IMAGE_INVALID, "이미지 해상도가 너무 큽니다.")
        # MPO의 여러 프레임은 깊이·미리보기용 보조 이미지라 애니메이션이 아니다. 첫 프레임(본 사진)만 쓴다.
        if image.format != "MPO" and getattr(image, "is_animated", False):
            raise BusinessException(ErrorCode.REVIEW_IMAGE_INVALID, "움직이는 이미지는 올릴 수 없습니다.")

        # JPEG(MPO 포함)는 디코딩 단계에서 1/2·1/4·1/8로 줄여 읽는다. exif_transpose가 먼저 전체를 풀면
        # thumbnail()의 축소 디코딩이 동작하지 않아 메모리를 원본 크기만큼 쓰기 때문이다. 다른 형식은 그대로 둔다.
        image.draft("RGB", (MAX_SIDE, MAX_SIDE))

        # EXIF 회전 정보를 픽셀에 반영한다. 다시 인코딩하면 EXIF가 빠져 폰 사진이 눕기 때문이다.
        image = ImageOps.exif_transpose(image)
        # webp는 RGB/RGBA만 저장하므로 CMYK·팔레트(P) 등은 변환한다. 투명도(RGBA)는 유지한다.
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "transparency" in image.info else "RGB")
        image.thumbnail((MAX_SIDE, MAX_SIDE))

        out = io.BytesIO()
        image.save(out, "WEBP", quality=WEBP_QUALITY)
        return out.getvalue()
    except BusinessException:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise BusinessException(ErrorCode.REVIEW_IMAGE_INVALID) from error


def prepare_review_image(file_storage) -> tuple[str, bytes]:
    """업로드 파일을 webp로 변환하고 새 저장소 키와 함께 반환한다. 저장은 호출자(service)가 한다.

    Args:
        file_storage: request.files의 werkzeug FileStorage.

    Returns:
        (key, webp 바이트). key는 `reviews/<uuid>.webp`.

    Raises:
        BusinessException: 원본이 MAX_UPLOAD_BYTES를 넘으면 REVIEW_IMAGE_TOO_LARGE,
            이미지가 아니면 REVIEW_IMAGE_INVALID.
    """
    # 한도보다 1바이트 더 읽어, 넘는 파일을 끝까지 메모리에 올리지 않고 판단한다.
    raw = file_storage.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BusinessException(ErrorCode.REVIEW_IMAGE_TOO_LARGE)

    return f"reviews/{uuid.uuid4().hex}.webp", convert_to_webp(raw)
