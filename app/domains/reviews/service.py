"""리뷰 생성·조회·수정·삭제와 행사별 평점 집계를 담당한다.

작성자 권한(본인 확인)을 여기서 검사하며, 실패는 BusinessException으로 올린다.

리뷰 사진 key 보호 (이슈 #63):
    리뷰 조회 응답에는 모든 사람의 사진 key가 그대로 보이므로 key는 비밀이 아니다.
    대신 클라이언트가 보낸 key를 리뷰에 새로 붙이는 길을 없앴다.
    - 작성: key를 받지 않는다. 사진 파일만 받고 key는 서버가 새로 만든다(_store_images).
    - 수정: 클라이언트가 보내는 key는 "남길 기존 사진"뿐이고, 그 리뷰에 원래 있던 key만 허용한다.
    그래서 남의 key를 알아도 내 리뷰에 붙인 뒤 수정·삭제로 남의 사진 파일을 지울 수 없다.
"""

import json

from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review
from app.domains.reviews.images import MAX_REVIEW_IMAGES, prepare_review_image
from app.domains.reviews.storage_client import delete_objects, put_object
from app.domains.users.models import User
from app.core.errors import BusinessException, ErrorCode
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

# MySQL의 중복 키(unique 위반) 오류 번호
_MYSQL_DUP_ENTRY = 1062


def create_review(data: dict, files=()) -> Review:
    """리뷰를 저장해 반환한다.

    Args:
        data: user_id, event_id, rating, content.
        files: 함께 올린 사진(werkzeug FileStorage) 목록. 최대 MAX_REVIEW_IMAGES장.

    Raises:
        BusinessException: 사용자가 없으면 USER_NOT_FOUND, 행사가 없으면 EVENT_NOT_FOUND,
            이미 같은 행사에 리뷰를 썼으면 REVIEW_ALREADY_EXISTS, 사진이 너무 많으면 COMMON_INVALID_INPUT.
            사진 오류는 _store_images 참고.
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

    if len(files) > MAX_REVIEW_IMAGES:
        raise _invalid_images(f"이미지는 최대 {MAX_REVIEW_IMAGES}장까지 첨부할 수 있습니다.")

    # 행사·중복 검사를 먼저 끝내, 거절될 요청으로는 저장소에 올리지 않는다.
    # 리뷰의 images에는 여기서 서버가 만든 key만 들어간다. 작성 요청에는 key를 적는 필드가 없다
    # (schemas.ReviewCreateSchema). 그래서 남의 사진 key를 내 리뷰에 붙일 수 없다.
    keys = _store_images(files)

    review = Review(
        user_id=data["user_id"],
        event_id=data["event_id"],
        rating=data["rating"],
        content=data["content"],
        images=keys,
    )

    db.session.add(review)

    try:
        _commit_or_delete(keys)
    except IntegrityError as e:
        # 동시 중복 제출은 unique 위반(1062)으로만 판단하고, FK 위반 등은 그대로 올린다.
        if _is_duplicate_entry(e):
            raise BusinessException(ErrorCode.REVIEW_ALREADY_EXISTS) from e

        raise

    return review


def _invalid_images(message: str) -> BusinessException:
    return BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"images": [message]}})


def _store_images(files) -> list[str]:
    """새 사진을 webp로 바꿔 저장소에 올리고 key 목록을 돌려준다.

    변환을 모두 끝낸 뒤 올려, 이미지가 아닌 파일이 섞이면 아무것도 올리지 않는다.
    올리다 실패하면 이미 올린 것을 지우고 예외를 그대로 올린다.

    Raises:
        BusinessException: prepare_review_image, storage_client.put_object 참고.
    """
    prepared = [prepare_review_image(file) for file in files]
    keys = []

    try:
        for key, data in prepared:
            put_object(key, data, "image/webp")
            keys.append(key)
    except Exception:
        delete_objects(keys)
        raise

    return keys


def _commit_or_delete(new_keys) -> None:
    """커밋한다. 실패하면 이번 요청에서 올린 사진을 지워 어디에도 붙지 않은 파일이 남지 않게 한다."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_objects(new_keys)
        raise


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
    """사용자가 쓴 리뷰를 최근 수정순으로 반환한다. 각 리뷰의 행사(event)도 함께 읽는다."""
    # 시각이 같으면 ID 내림차순으로 순서를 고정한다.
    reviews = db.session.scalars(
        select(Review)
        .options(selectinload(Review.event))  # 행사를 한 번의 추가 쿼리로 읽는다(N+1 방지)
        .where(Review.user_id == user_id)
        .order_by(Review.updated_at.desc(), Review.created_at.desc(), Review.id.desc())
    ).all()

    return reviews


def get_rating_info(event_id: int) -> dict:
    """행사의 평균 평점(소수 첫째 자리 반올림)과 리뷰 개수를 반환한다. 리뷰가 없으면 모두 0이다."""
    return get_rating_map([event_id])[event_id]


def get_rating_map(event_ids) -> dict[int, dict]:
    """여러 행사의 평균 평점과 리뷰 개수를 쿼리 한 번으로 구한다. 목록 카드와 상세가 같은 규칙을 쓴다.

    Returns:
        {event_id: {"average_rating", "review_count"}}. 리뷰가 없는 행사도 0.0, 0으로 들어 있다.
    """
    ratings = {event_id: {"average_rating": 0.0, "review_count": 0} for event_id in event_ids}

    if ratings:
        rows = db.session.execute(
            select(Review.event_id, func.avg(Review.rating), func.count(Review.id))
            .where(Review.event_id.in_(ratings))
            .group_by(Review.event_id)
        )

        for event_id, average, count in rows:
            ratings[event_id] = {"average_rating": round(float(average), 1), "review_count": count}

    return ratings


def update_review(review_id: int, user_id: int, data: dict, files=()) -> Review:
    """본인 리뷰에서 data에 있는 rating/content/images를 수정하고 files를 사진으로 덧붙인다.

    data["images"]는 남길 기존 사진 key 목록이다. 없으면 기존 사진을 모두 남긴다.

    Raises:
        BusinessException: 리뷰가 없으면 REVIEW_NOT_FOUND, 작성자가 아니면 REVIEW_FORBIDDEN,
            이 리뷰에 없는 key를 남기려 하거나 사진이 너무 많으면 COMMON_INVALID_INPUT.
            사진 오류는 _store_images 참고.
    """
    review = db.session.get(Review, review_id)

    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    current = review.images or []
    keep = data.get("images", current)

    # 클라이언트가 key를 보낼 수 있는 곳은 여기(남길 사진 목록)뿐이다. 새 사진 key는 서버만 만든다.
    # 그래서 이 리뷰에 원래 있던 key만 남길 수 있게 하면, 남의 key(응답에서 본 key)를 붙이는 길이 막힌다.
    # 평점·내용을 바꾸기 전에 검사해, 거절되면 리뷰가 하나도 바뀌지 않는다.
    if not set(keep) <= set(current):
        raise _invalid_images("이 리뷰에 없는 이미지는 남길 수 없습니다.")

    if len(keep) + len(files) > MAX_REVIEW_IMAGES:
        raise _invalid_images(f"이미지는 최대 {MAX_REVIEW_IMAGES}장까지 첨부할 수 있습니다.")

    if "rating" in data:
        review.rating = data["rating"]

    if "content" in data:
        review.content = data["content"]

    # 빠진 이미지는 커밋이 성공한 뒤에 저장소에서 지운다. 커밋 전에 지우면 실패 시 리뷰가 없는 파일을 가리킨다.
    # 다른 리뷰도 쓰는 이미지(예전 데이터)는 남긴다. 조회 실패로 새 사진이 남지 않게 올리기 전에 계산한다.
    removed_images = set(current) - set(keep)
    removed_images -= _keys_in_other_reviews(removed_images, Review.id != review.id)

    new_keys = _store_images(files)

    # 최종 목록 = 원래 있던 key 중 남길 것 + 서버가 방금 만든 key. 다른 출처의 key는 들어갈 수 없다.
    if "images" in data or new_keys:
        review.images = list(keep) + new_keys

    _commit_or_delete(new_keys)
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