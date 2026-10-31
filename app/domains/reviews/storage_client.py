"""S3 호환 저장소(Garage, AWS S3 등) 클라이언트.

auth/kakao_client.py, tour/client.py처럼 외부 통신만 맡는다. 이미지 변환은 images.py가 맡는다.
저장소를 옮기면 .env의 S3_* 값만 바꾸면 되며 코드와 DB는 그대로 둔다.
"""

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError
from flask import current_app

from app.core.errors import BusinessException, ErrorCode

# kakao_client.TIMEOUT(5초), tour client(timeout=10)와 같이 짧게 둔다. botocore 기본값은 60초다.
CONNECT_TIMEOUT = 5
READ_TIMEOUT = 10
# 최초 시도를 포함한 총 시도 횟수. botocore의 max_attempts는 재시도 횟수라 total_max_attempts로 지정한다.
MAX_ATTEMPTS = 2

# presigned URL 유효 시간(초). S3_PUBLIC_URL이 없을 때만 쓴다.
PRESIGNED_EXPIRES = 3600

# app.extensions에 클라이언트를 캐시하는 키. 앱마다 하나만 만든다.
_EXTENSION_KEY = "review_storage_client"


def is_configured() -> bool:
    """버킷과 접근 키가 모두 설정되어 있는지 확인한다."""
    config = current_app.config
    return bool(config.get("S3_BUCKET") and config.get("S3_ACCESS_KEY") and config.get("S3_SECRET_KEY"))


def _client():
    """앱에 캐시된 boto3 클라이언트를 반환한다. 처음 호출할 때 한 번만 만든다.

    boto3 클라이언트는 스레드 간 공유해도 안전하다. S3_ENDPOINT가 비어 있으면 boto3 기본값(AWS S3)을 쓴다.

    Raises:
        BusinessException: 버킷이나 키가 설정되지 않았으면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
    """
    if not is_configured():
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE)

    client = current_app.extensions.get(_EXTENSION_KEY)
    if client is None:
        config = current_app.config
        client = boto3.client(
            "s3",
            endpoint_url=config.get("S3_ENDPOINT") or None,
            region_name=config.get("S3_REGION") or None,
            aws_access_key_id=config["S3_ACCESS_KEY"],
            aws_secret_access_key=config["S3_SECRET_KEY"],
            config=BotoConfig(
                connect_timeout=CONNECT_TIMEOUT,
                read_timeout=READ_TIMEOUT,
                retries={"total_max_attempts": MAX_ATTEMPTS, "mode": "standard"},
            ),
        )
        current_app.extensions[_EXTENSION_KEY] = client
    return client


def put_object(key: str, data: bytes, content_type: str) -> None:
    """객체를 저장한다.

    Raises:
        BusinessException: 설정 누락이나 통신 실패면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
    """
    client = _client()
    try:
        client.put_object(Bucket=current_app.config["S3_BUCKET"], Key=key, Body=data, ContentType=content_type)
    except (BotoCoreError, ClientError):
        # 오류 메시지에 엔드포인트·버킷 정보가 담길 수 있어 응답에는 넣지 않고 로그에만 남긴다.
        current_app.logger.error("리뷰 이미지 저장 실패: key=%s", key, exc_info=True)
        raise BusinessException(ErrorCode.REVIEW_IMAGE_STORAGE_UNAVAILABLE) from None


def delete_objects(keys) -> None:
    """객체를 지운다. 리뷰 수정·삭제가 커밋된 뒤에 호출한다.

    리뷰 변경은 이미 끝났으므로 실패해도 예외를 올리지 않고 로그만 남긴다.
    남은 파일은 어디서도 참조되지 않을 뿐 응답에는 영향이 없다.
    """
    keys = list(keys)
    if not keys:
        return
    try:
        _client().delete_objects(
            Bucket=current_app.config["S3_BUCKET"],
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
    except (BusinessException, BotoCoreError, ClientError):
        current_app.logger.warning("리뷰 이미지 삭제 실패(%d개)", len(keys), exc_info=True)


def object_url(key: str) -> str | None:
    """저장소 키를 브라우저가 열 수 있는 URL로 바꾼다. 네트워크 요청은 하지 않는다.

    S3_PUBLIC_URL이 있으면 그 뒤에 키를 붙이고, 없으면 presigned URL을 만든다.
    조회 응답이 저장소 설정 문제로 실패하지 않도록, URL을 만들 수 없으면 None을 반환한다.
    """
    public_url = current_app.config.get("S3_PUBLIC_URL")
    if public_url:
        return f"{public_url.rstrip('/')}/{key}"
    if not is_configured():
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
