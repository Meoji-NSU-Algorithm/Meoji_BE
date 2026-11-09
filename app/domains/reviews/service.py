"""리뷰 생성·조회·수정·삭제와 행사별 평점 집계를 담당한다.

작성자 권한(본인 확인)을 여기서 검사하며, 실패는 BusinessException으로 올린다.
"""

import json

from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review
from app.domains.reviews.images import prepare_review_image
from app.domains.reviews.storage_client import delete_objects, put_object
from app.domains.users.models import User
from app.core.errors import BusinessException, ErrorCode
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

# MySQL의 중복 키(unique 위반) 오류 번호
_MYSQL_DUP_ENTRY = 1062


def create_review(data: dict) -> Review:
    """리뷰를 저장해 반환한다.

    Args:
        data: user_id, event_id, rating, content.

    Raises:
        BusinessException: 사용자가 없으면 USER_NOT_FOUND, 행사가 없으면 EVENT_NOT_FOUND,
            이미 같은 행사에 리뷰를 썼으면 REVIEW_ALREADY_EXISTS.
    """
    user = db.session.get(User, data["user_id"])

    if user is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)

    event = db.session.get(Event, data["event_id"])

    if event is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    # 사용자당 행사별 리뷰는 하나만 허용한다.
    already = db.session.scalar(
        select(Review.id).where(Review.user_id == data["user_id"], Review.event_id == data["event_id"])
    )

    if already is not None:
        raise BusinessException(ErrorCode.REVIEW_ALREADY_EXISTS)

    review = Review(
        user_id=data["user_id"],
        event_id=data["event_id"],
        rating=data["rating"],
        content=data["content"],
        images=data.get("images", []),
    )

    db.session.add(review)

    try:
        db.session.commit()
    except IntegrityError as e:
        db.session.rollback()

        # 동시 중복 제출은 unique 위반(1062)으로만 판단하고, FK 위반 등은 그대로 올린다.
        if _is_duplicate_entry(e):
            raise BusinessException(ErrorCode.REVIEW_ALREADY_EXISTS) from e

        raise

    return review


def upload_image(file_storage) -> str:
    """리뷰에 붙일 이미지 한 장을 webp로 변환해 저장하고 저장소 key를 반환한다.

    Args:
        file_storage: request.files["image"]. 필드가 없으면 None.

    Raises:
        BusinessException: 파일이 없으면 COMMON_INVALID_INPUT, 저장소 오류면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
            그 밖은 prepare_review_image 참고.
    """
    if file_storage is None or not file_storage.filename:
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"image": ["이미지 파일이 필요합니다."]}})

    # 변환을 먼저 끝내 이미지가 아닌 파일로는 저장소 설정 오류까지 가지 않게 한다.
    key, data = prepare_review_image(file_storage)
    put_object(key, data, "image/webp")

    return key


def _keys_in_other_reviews(keys, *exclude) -> set[str]:
    """keys 중 다른 리뷰가 쓰고 있는 key. exclude로 자기 리뷰를 뺀다(예: Review.id != review.id)."""
    keys = set(keys)

    if not keys:
        return set()

    # MySQL 8.0.17+ JSON_OVERLAPS: images 배열에 keys 중 하나라도 있는 리뷰
    rows = db.session.scalars(
        select(Review.images).where(func.json_overlaps(Review.images, json.dumps(sorted(keys))), *exclude)
    )

    return keys & {key for images in rows for key in images or []}


def image_keys_to_delete_on_withdraw(user_id: int) -> set[str]:
    """탈퇴로 지울 이미지 key. 다른 사용자 리뷰가 쓰는 key는 남긴다. 리뷰가 지워지기 전에 호출한다."""
    rows = db.session.scalars(select(Review.images).where(Review.user_id == user_id))
    keys = {key for images in rows for key in images or []}

    return keys - _keys_in_other_reviews(keys, Review.user_id != user_id)


def _is_duplicate_entry(error: IntegrityError) -> bool:
    """IntegrityError가 MySQL unique 위반(errno 1062)인지 확인한다."""
    args = getattr(error.orig, "args", ())

    return bool(args) and args[0] == _MYSQL_DUP_ENTRY


def get_reviews_by_event(event_id: int) -> list[Review]:
    """행사의 리뷰를 최근 수정순으로 반환한다. 행사 존재 여부는 확인하지 않는다."""
    reviews = db.session.scalars(
        select(Review)
        .where(Review.event_id == event_id)
        .order_by(Review.updated_at.desc(), Review.created_at.desc(), Review.id.desc())
    ).all()

    return reviews


def get_my_reviews(user_id: int) -> list[Review]:
    """사용자가 쓴 리뷰를 최근 수정순으로 반환한다."""
    # 시각이 같으면 ID 내림차순으로 순서를 고정한다.
    reviews = db.session.scalars(
        select(Review)
        .where(Review.user_id == user_id)
        .order_by(Review.updated_at.desc(), Review.created_at.desc(), Review.id.desc())
    ).all()

    return reviews


def get_rating_info(event_id: int) -> dict:
    """행사의 평균 평점(소수 첫째 자리 반올림)과 리뷰 개수를 반환한다. 리뷰가 없으면 모두 0이다."""
    result = db.session.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .where(Review.event_id == event_id)
    ).first()

    average_rating = result[0]
    review_count = result[1]

    if average_rating is None:
        average_rating = 0
    else:
        average_rating = round(float(average_rating), 1)

    return {
        "average_rating": average_rating,
        "review_count": review_count,
    }


def update_review(review_id: int, user_id: int, data: dict) -> Review:
    """본인 리뷰에서 data에 있는 rating/content만 수정한다.

    Raises:
        BusinessException: 리뷰가 없으면 REVIEW_NOT_FOUND, 작성자가 아니면 REVIEW_FORBIDDEN.
    """
    review = db.session.get(Review, review_id)

    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    if "rating" in data:
        review.rating = data["rating"]

    if "content" in data:
        review.content = data["content"]

    # 빠진 이미지는 커밋이 성공한 뒤에 저장소에서 지운다. 커밋 전에 지우면 실패 시 리뷰가 없는 파일을 가리킨다.
    removed_images = []
    if "images" in data:
        removed_images = {key for key in (review.images or []) if key not in data["images"]}
        removed_images -= _keys_in_other_reviews(removed_images, Review.id != review.id)
        review.images = data["images"]

    db.session.commit()
    delete_objects(removed_images)

    return review


def delete_review(review_id: int, user_id: int) -> Review:
    """본인 리뷰를 삭제하고 삭제된 리뷰를 반환한다.

    Raises:
        BusinessException: 리뷰가 없으면 REVIEW_NOT_FOUND, 작성자가 아니면 REVIEW_FORBIDDEN.
    """
    review = db.session.get(Review, review_id)

    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    # 다른 리뷰도 쓰는 이미지는 남긴다.
    images = set(review.images or [])
    images -= _keys_in_other_reviews(images, Review.id != review.id)

    db.session.delete(review)
    db.session.commit()
    # update_review와 같이 커밋 성공 뒤에 저장소 파일을 지운다.
    delete_objects(images)

    return review