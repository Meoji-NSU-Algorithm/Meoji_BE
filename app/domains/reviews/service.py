"""리뷰 생성·조회·수정·삭제와 행사별 평점 집계를 담당한다.

작성자 권한(본인 확인)을 여기서 검사하며, 실패는 BusinessException으로 올린다.
"""

from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review
from app.domains.reviews.images import delete_review_images, upload_review_image
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

    변환과 저장소 통신은 images 모듈이 맡고, 여기서는 요청에 파일이 있는지만 확인한다.

    Args:
        file_storage: request.files["image"]. 필드가 없으면 None.

    Raises:
        BusinessException: 파일이 없으면 COMMON_INVALID_INPUT. 그 밖은 upload_review_image 참고.
    """
    if file_storage is None or not file_storage.filename:
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"image": ["이미지 파일이 필요합니다."]}})

    return upload_review_image(file_storage)


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
        removed_images = [key for key in (review.images or []) if key not in data["images"]]
        review.images = data["images"]

    db.session.commit()
    delete_review_images(removed_images)

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

    db.session.delete(review)
    db.session.commit()
    # update_review와 같이 커밋 성공 뒤에 저장소 파일을 지운다.
    delete_review_images(review.images or [])

    return review