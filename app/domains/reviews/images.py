"""리뷰 이미지 변환과 S3 호환 저장소(Garage, AWS S3 등) 업로드·삭제를 담당한다.

업로드한 원본은 저장하지 않고, 긴 변을 줄여 webp로 다시 인코딩한 결과만 저장한다.
다시 인코딩하면 EXIF(촬영 위치 등)가 빠지고 이미지가 아닌 파일은 여기서 걸러진다.
DB에는 저장소 키(`reviews/<uuid>.webp`)만 저장하고 URL은 응답 시점에 만든다.
저장소를 옮기면 .env의 S3_* 값만 바꾸면 되며 DB는 그대로 둔다.
"""

import io
import re
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app
from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.errors import BusinessException, ErrorCode

# 리뷰 한 건에 붙일 수 있는 최대 장수
MAX_REVIEW_IMAGES = 5

# 변환 전 원본 한 장의 최대 크기. 변환하려면 메모리에 올려야 하므로 원본 기준으로 막는다.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 저장할 이미지의 긴 변(px). 폰 사진(4000px 안팎)을 이 크기로 줄이는 것이 용량 절감의 대부분이다.
MAX_SIDE = 1600

WEBP_QUALITY = 80

# 압축은 작지만 풀면 거대한 이미지(픽셀 폭탄)를 막는다. 넘으면 Pillow가 DecompressionBombError를 낸다.
# Pillow 전역 설정이라 이 모듈을 import하는 순간 앱 전체에 적용된다.
Image.MAX_IMAGE_PIXELS = 40_000_000

# 업로드를 받는 형식. 움직이는 GIF는 지원하지 않는다.
_ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")

# 이 서버가 만든 키만 리뷰에 연결할 수 있게 형식을 고정한다. 외부 URL이나 다른 경로를 막는다.
KEY_PATTERN = re.compile(r"^reviews/[0-9a-f]{32}\.webp$")

# presigned URL 유효 시간(초). S3_PUBLIC_URL이 없을 때만 쓴다.
_PRESIGNED_EXPIRES = 3600


def convert_to_webp(raw: bytes) -> bytes:
    """이미지 바이트를 회전 보정·리사이즈한 webp 바이트로 바꾼다.

    Raises:
        BusinessException: 이미지가 아니거나 지원하지 않는 형식이면 REVIEW_IMAGE_INVALID.
    """
    try:
        # verify()는 파일 구조만 검사하고 이미지를 못 쓰게 만들므로 다시 연다.
        Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS).verify()
        image = Image.open(io.BytesIO(raw), formats=_ACCEPTED_FORMATS)
        if getattr(image, "is_animated", False):
            raise BusinessException(ErrorCode.REVIEW_IMAGE_INVALID, "움직이는 이미지는 올릴 수 없습니다.")

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


def _client():
    """설정의 S3_* 값으로 boto3 클라이언트를 만든다.

    S3_ENDPOINT가 비어 있으면 boto3 기본값(AWS S3)을 쓴다.

    Raises:
        BusinessException: 버킷이나 키가 설정되지 않았으면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
    """
    config = current_app.config
    if not (config.get("S3_BUCKET") and config.get("S3_ACCESS_KEY") and config.get("S3_SECRET_KEY")):
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE)
    return boto3.client(
        "s3",
        endpoint_url=config.get("S3_ENDPOINT") or None,
        region_name=config.get("S3_REGION") or None,
        aws_access_key_id=config["S3_ACCESS_KEY"],
        aws_secret_access_key=config["S3_SECRET_KEY"],
    )


def upload_review_image(file_storage) -> str:
    """업로드 파일을 webp로 변환해 저장소에 올리고 저장소 키를 반환한다.

    Args:
        file_storage: request.files의 werkzeug FileStorage.

    Raises:
        BusinessException: 원본이 MAX_UPLOAD_BYTES를 넘으면 REVIEW_IMAGE_TOO_LARGE,
            이미지가 아니면 REVIEW_IMAGE_INVALID, 저장소 오류면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
    """
    # 한도보다 1바이트 더 읽어, 넘는 파일을 끝까지 메모리에 올리지 않고 판단한다.
    raw = file_storage.stream.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise BusinessException(ErrorCode.REVIEW_IMAGE_TOO_LARGE)

    data = convert_to_webp(raw)
    key = f"reviews/{uuid.uuid4().hex}.webp"
    # 변환을 먼저 끝내 이미지가 아닌 파일로는 저장소 설정 오류까지 가지 않게 한다.
    client = _client()
    try:
        client.put_object(Bucket=current_app.config["S3_BUCKET"], Key=key, Body=data, ContentType="image/webp")
    except (BotoCoreError, ClientError) as error:
        # 오류 메시지에 엔드포인트·버킷 정보가 담길 수 있어 응답에는 넣지 않고 로그에만 남긴다.
        current_app.logger.error("리뷰 이미지 업로드 실패: %s", error)
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE) from None
    return key


def image_url(key: str) -> str:
    """저장소 키를 브라우저가 열 수 있는 URL로 바꾼다.

    S3_PUBLIC_URL이 있으면 그 뒤에 키를 붙이고, 없으면 presigned URL을 만든다.
    """
    public_url = current_app.config.get("S3_PUBLIC_URL")
    if public_url:
        return f"{public_url.rstrip('/')}/{key}"
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": current_app.config["S3_BUCKET"], "Key": key},
        ExpiresIn=_PRESIGNED_EXPIRES,
    )


def delete_review_images(keys) -> None:
    """저장소에서 이미지를 지운다. 리뷰 수정·삭제가 커밋된 뒤에 호출한다.

    리뷰 변경은 이미 끝났으므로 실패해도 예외를 올리지 않고 로그만 남긴다.
    남은 파일은 어디서도 참조되지 않을 뿐 응답에는 영향이 없다.
    """
    if not keys:
        return
    try:
        client = _client()
        client.delete_objects(
            Bucket=current_app.config["S3_BUCKET"],
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
    except (BusinessException, BotoCoreError, ClientError) as error:
        current_app.logger.warning("리뷰 이미지 삭제 실패(%d개): %s", len(keys), error)
