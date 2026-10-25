"""리뷰 생성·조회·수정·삭제와 행사별 평점 집계를 담당한다.

작성자 권한(본인 확인)을 여기서 검사하며, 실패는 BusinessException으로 올린다.
"""

from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review
from app.domains.users.models import User
from app.core.errors import BusinessException, ErrorCode
from sqlalchemy import func, select


def create_review(data: dict) -> Review:
    """리뷰를 저장해 반환한다.

    Args:
        data: user_id, event_id, rating, content.

    Raises:
        BusinessException: 사용자가 없으면 USER_NOT_FOUND, 행사가 없으면 EVENT_NOT_FOUND.
    """
    user = db.session.get(User, data["user_id"])

    if user is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)

    event = db.session.get(Event, data["event_id"])

    if event is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    review = Review(
        user_id=data["user_id"],
        event_id=data["event_id"],
        rating=data["rating"],
        content=data["content"],
    )

    db.session.add(review)
    db.session.commit()

    return review


def ensure_event_exists(event_id: int) -> None:
    """행사가 없으면 EVENT_NOT_FOUND를 발생시킨다."""
    if db.session.get(Event, event_id) is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)


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

    db.session.commit()

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

    return review