"""리뷰 이미지 제한과 저장소 key 발급을 담당한다. 변환은 core/images.py, 저장소 통신은 core/storage.py가 맡는다.

DB에는 저장소 키(`reviews/<uuid>.webp`)만 저장하고 URL은 응답 시점에 만든다.
"""

import re
import uuid

from app.core.images import convert_to_webp, read_upload

# 리뷰 한 건에 붙일 수 있는 최대 장수
MAX_REVIEW_IMAGES = 5

# 변환 전 원본 한 장의 최대 크기. 변환하려면 메모리에 올려야 하므로 원본 기준으로 막는다.
REVIEW_MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# 저장할 이미지의 긴 변(px). 폰 사진(4000px 안팎)을 이 크기로 줄이는 것이 용량 절감의 대부분이다.
REVIEW_MAX_SIDE = 1600

# 이 서버가 만든 키만 리뷰에 연결할 수 있게 형식을 고정한다. 외부 URL이나 다른 경로를 막는다.
KEY_PATTERN = re.compile(r"^reviews/[0-9a-f]{32}\.webp$")


def prepare_review_image(file_storage) -> tuple[str, bytes]:
    """업로드 파일을 webp로 바꿔 새 저장소 key와 함께 돌려준다. 저장은 호출자가 한다.

    Raises:
        BusinessException: 원본이 REVIEW_MAX_UPLOAD_BYTES를 넘으면 IMAGE_TOO_LARGE,
            이미지가 아니면 IMAGE_INVALID.
    """
    raw = read_upload(file_storage, max_bytes=REVIEW_MAX_UPLOAD_BYTES)

    # key(저장소 파일 이름)는 서버가 랜덤으로 만든다. 사용자가 보낸 파일 이름은 쓰지 않는다.
    # 사용자가 이름을 정할 수 있으면 남의 파일과 같은 이름으로 덮어쓰거나, 남의 key를 흉내 낼 수 있기 때문이다.
    return f"reviews/{uuid.uuid4().hex}.webp", convert_to_webp(raw, max_side=REVIEW_MAX_SIDE)
