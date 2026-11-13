"""S3 호환 저장소(Garage, AWS S3 등) 클라이언트.

auth/kakao_client.py처럼 외부 통신만 맡는다. 이미지 변환은 images.py가 맡는다.
저장소를 옮기면 .env의 S3_* 값만 바꾸면 되며 코드와 DB는 그대로 둔다.
"""

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app

from app.core.config import _is_placeholder
from app.core.errors import BusinessException, ErrorCode

# presigned URL 유효 시간(초). S3_PUBLIC_URL이 없을 때만 쓴다.
PRESIGNED_EXPIRES = 3600


def _configured() -> bool:
    """버킷·키가 채워져 있고, .env.example의 자리표시 값(NEED_TO_SET 등)이 남아 있지 않은지 본다."""
    config = current_app.config
    required = [config.get(name) for name in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")]
    # 비어 있는 S3_ENDPOINT는 AWS S3라 허용하지만, 자리표시 값이면 boto3가 ValueError를 낸다.
    endpoint = config.get("S3_ENDPOINT") or ""
    return all(value and not _is_placeholder(value) for value in required) and not _is_placeholder(endpoint)


def _client():
    """앱마다 한 번 만든 boto3 클라이언트를 돌려준다(스레드 간 공유 가능).

    Raises:
        BusinessException: 버킷이나 키가 설정되지 않았으면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
    """
    if not _configured():
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE)

    client = current_app.extensions.get("review_storage_client")
    if client is None:
        config = current_app.config
        client = boto3.client(
            "s3",
            # 비어 있으면 boto3 기본값(AWS S3)
            endpoint_url=config.get("S3_ENDPOINT") or None,
            region_name=config.get("S3_REGION") or None,
            aws_access_key_id=config["S3_ACCESS_KEY"],
            aws_secret_access_key=config["S3_SECRET_KEY"],
            # botocore 기본 타임아웃은 60초라 저장소가 멈추면 요청이 오래 묶인다. 카카오·TourAPI처럼 짧게 둔다.
            config=BotoConfig(connect_timeout=5, read_timeout=10, retries={"total_max_attempts": 2}),
        )
        current_app.extensions["review_storage_client"] = client
    return client


def put_object(key: str, data: bytes, content_type: str) -> None:
    """Raises: BusinessException: 설정 누락이나 통신 실패면 REVIEW_IMAGE_STORAGE_UNAVAILABLE."""
    client = _client()
    try:
        client.put_object(Bucket=current_app.config["S3_BUCKET"], Key=key, Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError):
        # 오류 메시지에 엔드포인트·버킷 정보가 담길 수 있어 응답에는 넣지 않고 로그에만 남긴다.
        current_app.logger.error("리뷰 이미지 저장 실패: key=%s", key, exc_info=True)
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE) from None


def delete_objects(keys) -> None:
    """객체를 지운다. 리뷰 변경이 커밋된 뒤에 호출하므로 실패해도 예외 없이 로그만 남긴다."""
    keys = list(keys)
    if not keys:
        return
    try:
        _client().delete_objects(
            Bucket=current_app.config["S3_BUCKET"],
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
    except Exception:
        # 커밋 뒤 정리라 어떤 오류든 요청(탈퇴 등)을 실패시키지 않는다. 남은 파일은 참조되지 않을 뿐이다.
        current_app.logger.warning("리뷰 이미지 삭제 실패(%d개)", len(keys), exc_info=True)


def object_url(key: str) -> str | None:
    """브라우저가 열 수 있는 URL. S3_PUBLIC_URL이 있으면 그 뒤에 key를 붙이고, 없으면 presigned URL.

    조회 응답이 저장소 문제로 실패하지 않도록 URL을 만들 수 없으면 None을 돌려준다.
    """
    public_url = current_app.config.get("S3_PUBLIC_URL")
    if public_url:
        return f"{public_url.rstrip('/')}/{key}"
    if not _configured():
        return None
    try:
        return _client().generate_presigned_url(
            "get_object",
            Params={"Bucket": current_app.config["S3_BUCKET"], "Key": key},
            ExpiresIn=PRESIGNED_EXPIRES,
        )
    except (BotoCoreError, ClientError):
        current_app.logger.warning("리뷰 이미지 URL 생성 실패: key=%s", key, exc_info=True)
        return None
