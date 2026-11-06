"""리뷰 생성·조회·수정·삭제와 행사별 평점 집계를 담당한다.

작성자 권한(본인 확인)을 여기서 검사하며, 실패는 BusinessException으로 올린다.
리뷰를 돌려주는 함수는 응답용 작성자(review.author_info)와 이미지 URL(review.image_items)도 채워서 돌려준다.
"""

import json
from datetime import datetime, timedelta, timezone

from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review, ReviewImageUpload
from app.domains.reviews import storage_client
from app.domains.reviews.images import prepare_review_image
from app.domains.users.models import User
from app.core.errors import BusinessException, ErrorCode
from sqlalchemy import delete, func, select
from flask import current_app
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

# MySQL의 중복 키(unique 위반) 오류 번호
_MYSQL_DUP_ENTRY = 1062

# 업로드 후 이 시간 안에 리뷰에 붙지 않으면 정리한다. 작성 화면에 머무는 시간보다 넉넉하게 둔다.
UNATTACHED_UPLOAD_TTL = timedelta(hours=24)

# 사용자당 리뷰에 아직 붙이지 않은 업로드 최대 개수. 리뷰 한 개의 최대 장수(images.MAX_REVIEW_IMAGES=5)의
# 4배로, 작성 화면을 몇 번 오가며 사진을 바꿔도 막히지 않을 만큼 둔다.
MAX_UNATTACHED_UPLOADS = 20

# 한 번에 정리하는 최대 개수. 정리 중 잡는 행 잠금이 길어지지 않게 나눠서 지운다.
_CLEANUP_BATCH = 50


def create_review(data: dict) -> Review:
    """리뷰를 저장해 반환한다.

    Args:
        data: user_id, event_id, rating, content, images(선택, 저장소 key 목록).

    Raises:
        BusinessException: 사용자가 없으면 USER_NOT_FOUND, 행사가 없으면 EVENT_NOT_FOUND,
            이미 같은 행사에 리뷰를 썼으면 REVIEW_ALREADY_EXISTS,
            다른 리뷰에 이미 붙은 이미지면 REVIEW_IMAGE_ALREADY_ATTACHED,
            직접 올린 미첨부 이미지가 아니면 REVIEW_IMAGE_NOT_UPLOADED.
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

    images = data.get("images", [])
    _ensure_images_not_attached(images)
    # 리뷰를 세션에 넣기 전에 처리한다. 넣은 뒤에 DML을 실행하면 autoflush로 INSERT가 먼저 나가
    # 동시 중복 제출의 unique 위반이 아래 try 바깥에서 터져 409 대신 500이 된다.
    _claim_uploads(images, data["user_id"])

    review = Review(
        user_id=data["user_id"],
        event_id=data["event_id"],
        rating=data["rating"],
        content=data["content"],
        images=images,
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

    return _with_response_fields([review])[0]


def upload_image(file_storage, user_id: int) -> dict:
    """리뷰에 붙일 이미지 한 장을 webp로 변환해 저장하고 {key, url}을 반환한다.

    변환은 images 모듈, 저장소 통신은 storage_client가 맡고, 여기서는 요청에 파일이 있는지만 확인한다.

    Args:
        file_storage: request.files["image"]. 필드가 없으면 None.
        user_id: 업로드한 사용자. 리뷰에 붙지 않은 업로드를 정리할 때 기록으로 남긴다.

    Raises:
        BusinessException: 파일이 없으면 COMMON_INVALID_INPUT, 저장소 오류면 REVIEW_IMAGE_STORAGE_UNAVAILABLE.
            그 밖은 prepare_review_image 참고.
    """
    if file_storage is None or not file_storage.filename:
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"image": ["이미지 파일이 필요합니다."]}})

    _ensure_upload_quota(user_id)

    # 변환을 먼저 끝내 이미지가 아닌 파일로는 저장소 설정 오류까지 가지 않게 한다.
    key, data = prepare_review_image(file_storage)

    # 기록을 먼저 남겨, 저장 뒤 기록이 실패해 추적되지 않는 파일이 생기지 않게 한다.
    # 저장이 실패하면 기록만 남고, 정리 때 없는 파일을 지우려다 넘어갈 뿐이다.
    db.session.add(ReviewImageUpload(key=key, user_id=user_id))
    db.session.commit()
    storage_client.put_object(key, data, "image/webp")

    return {"key": key, "url": storage_client.object_url(key)}


def _ensure_upload_quota(user_id: int) -> None:
    """리뷰에 아직 붙지 않은 이 사용자의 업로드가 MAX_UNATTACHED_UPLOADS개 미만인지 확인한다.

    정리 대상(UNATTACHED_UPLOAD_TTL 경과)은 곧 지워지므로 세지 않는다. 동시 업로드로 한도를 몇 장 넘길 수는
    있지만, 반복 업로드로 저장소를 무한히 채우는 것을 막는 것이 목적이라 잠금은 걸지 않는다.

    Raises:
        BusinessException: 한도에 이르렀으면 REVIEW_IMAGE_UPLOAD_LIMIT(429).
    """
    since = datetime.now(timezone.utc).replace(tzinfo=None) - UNATTACHED_UPLOAD_TTL
    pending = db.session.scalar(
        select(func.count()).select_from(ReviewImageUpload).where(
            ReviewImageUpload.user_id == user_id,
            ReviewImageUpload.created_at >= since,
        )
    )

    if pending >= MAX_UNATTACHED_UPLOADS:
        raise BusinessException(ErrorCode.REVIEW_IMAGE_UPLOAD_LIMIT)


def _claim_uploads(keys, user_id: int) -> None:
    """새로 붙이는 key가 이 사용자가 올린 미첨부 업로드인지 확인하고 업로드 기록을 지운다.

    기록 삭제가 확인을 겸한다. 지운 행 수가 key 수보다 적으면 업로드한 적 없는 key, 남이 올린 key,
    정리된(24시간 지난) key가 섞인 것이다. 같은 key를 동시에 붙이면 뒤 요청은 앞 요청의 행 잠금을
    기다렸다가 0행을 지우게 되어 거부된다. 기록 삭제는 리뷰 저장과 같은 트랜잭션에서 커밋된다.

    Raises:
        BusinessException: REVIEW_IMAGE_NOT_UPLOADED. 세션은 롤백한다.
    """
    keys = list(keys)

    if not keys:
        return

    result = db.session.execute(
        delete(ReviewImageUpload).where(ReviewImageUpload.key.in_(keys), ReviewImageUpload.user_id == user_id)
    )

    if result.rowcount != len(keys):
        db.session.rollback()
        raise BusinessException(ErrorCode.REVIEW_IMAGE_NOT_UPLOADED)


def cleanup_unattached_uploads(now: datetime | None = None) -> int:
    """UNATTACHED_UPLOAD_TTL이 지나도록 리뷰에 붙지 않은 업로드를 저장소와 기록에서 지운다.

    reviews.scheduler가 주기적으로 호출한다. 한 번에 _CLEANUP_BATCH개까지 처리하고 지운 파일 수를 반환한다.
    파일을 먼저 지우고 삭제에 성공한 key의 기록만 지운다. 저장소 삭제가 실패한 key는 기록이 남아
    다음 정리 때 다시 시도된다. 실패해도 예외를 올리지 않고 로그만 남긴다.
    """
    # created_at은 UTC naive로 저장되므로 같은 형식으로 비교한다.
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        # 행을 잠가, 정리하는 동안 같은 key를 리뷰에 붙이는 요청이 끼어들지 못하게 한다.
        # 그 요청은 정리가 끝난 뒤 기록이 없어 REVIEW_IMAGE_NOT_UPLOADED로 거부된다.
        # 이 잠금은 아래 저장소(S3) 삭제 호출 동안에도 유지된다(storage_client 타임아웃 기준 최대 약 30초).
        # 잠기는 행은 TTL이 지나 곧 지워질 업로드뿐이라 기다리는 요청도 어차피 거부될 요청이다.
        # 잠금 없이 처리하면 S3 삭제와 리뷰 첨부가 경합해 깨진 사진이 남을 수 있어 유지한다. (#47)
        keys = list(db.session.scalars(
            select(ReviewImageUpload.key)
            .where(ReviewImageUpload.created_at < now - UNATTACHED_UPLOAD_TTL)
            .order_by(ReviewImageUpload.created_at)
            .limit(_CLEANUP_BATCH)
            .with_for_update()
        ))

        if not keys:
            db.session.rollback()
            return 0

        # 기록이 남았더라도 리뷰에 붙어 있으면 파일은 지우지 않고 기록만 지운다.
        unattached = set(keys) - _keys_attached_elsewhere(keys)
        deleted = storage_client.delete_objects(sorted(unattached))
        done = deleted | (set(keys) - unattached)

        if done:
            db.session.execute(delete(ReviewImageUpload).where(ReviewImageUpload.key.in_(done)))
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning("미첨부 리뷰 이미지 정리 실패", exc_info=True)
        return 0

    return len(deleted)


def _is_duplicate_entry(error: IntegrityError) -> bool:
    """IntegrityError가 MySQL unique 위반(errno 1062)인지 확인한다."""
    args = getattr(error.orig, "args", ())

    return bool(args) and args[0] == _MYSQL_DUP_ENTRY


def _keys_attached_elsewhere(keys, exclude_review_id: int | None = None) -> set[str]:
    """keys 중 다른 리뷰(exclude_review_id 제외)의 images에 들어 있는 key를 반환한다."""
    keys = list(keys)

    if not keys:
        return set()

    # JSON 배열끼리 겹치는 원소가 있는 리뷰만 고른다. (MySQL 8.0.17+ JSON_OVERLAPS)
    query = select(Review.images).where(func.json_overlaps(Review.images, json.dumps(keys)))

    if exclude_review_id is not None:
        query = query.where(Review.id != exclude_review_id)

    attached = set()

    for images in db.session.scalars(query):
        attached.update(images or [])

    return attached & set(keys)


def _ensure_images_not_attached(keys, review_id: int | None = None) -> None:
    """다른 리뷰에 이미 붙은 key가 있으면 거부한다.

    리뷰 응답의 key는 누구나 볼 수 있으므로, 남의 key를 자기 리뷰에 붙인 뒤 수정·삭제해
    남의 이미지를 지우는 것을 막는다. 아직 어디에도 붙지 않은 key는 업로드한 사람만 알고 있다.

    Raises:
        BusinessException: REVIEW_IMAGE_ALREADY_ATTACHED.
    """
    if _keys_attached_elsewhere(keys, review_id):
        raise BusinessException(ErrorCode.REVIEW_IMAGE_ALREADY_ATTACHED)


def _delete_unreferenced_images(keys) -> None:
    """다른 리뷰가 참조하지 않는 key만 저장소에서 지운다. 커밋이 끝난 뒤에 호출한다.

    리뷰 변경은 이미 커밋됐으므로, storage_client.delete_objects처럼 참조 확인이 실패해도
    예외를 올리지 않고 로그만 남긴다. 확인하지 못한 key는 지우지 않는다(남의 이미지를 지우지 않는 쪽).
    """
    keys = set(keys)

    if not keys:
        return

    try:
        unreferenced = keys - _keys_attached_elsewhere(keys)
    except SQLAlchemyError:
        current_app.logger.warning("리뷰 이미지 참조 확인 실패(%d개), 삭제를 건너뜀", len(keys), exc_info=True)
        return

    storage_client.delete_objects(sorted(unreferenced))


def get_image_keys_by_user(user_id: int) -> list[str]:
    """사용자의 모든 리뷰에 붙은 이미지 key를 반환한다. 탈퇴로 리뷰가 지워지기 전에 읽어 둔다."""
    keys = []

    for images in db.session.scalars(select(Review.images).where(Review.user_id == user_id)):
        keys.extend(images or [])

    return keys


def delete_images_after_commit(keys) -> None:
    """다른 도메인에서 리뷰 삭제를 커밋한 뒤 이미지를 지울 때 쓴다. 실패해도 예외를 올리지 않는다."""
    _delete_unreferenced_images(keys)


def _with_response_fields(reviews: list[Review]) -> list[Review]:
    """응답용 작성자(review.author_info)와 [{key, url}](review.image_items)를 채운다.

    스키마는 이 값을 그대로 직렬화한다. 작성자는 리뷰마다 조회하지 않고 한 번에 모아서 조회한다.
    """
    user_ids = {review.user_id for review in reviews}
    authors = {}

    if user_ids:
        authors = {user.id: user for user in db.session.scalars(select(User).where(User.id.in_(user_ids)))}

    for review in reviews:
        review.author_info = authors.get(review.user_id)
        review.image_items = [{"key": key, "url": storage_client.object_url(key)} for key in (review.images or [])]

    return reviews


def get_reviews_by_event(event_id: int) -> list[Review]:
    """행사의 리뷰를 최근 수정순으로 반환한다. 행사 존재 여부는 확인하지 않는다."""
    reviews = db.session.scalars(
        select(Review)
        .where(Review.event_id == event_id)
        .order_by(Review.updated_at.desc(), Review.created_at.desc(), Review.id.desc())
    ).all()

    return _with_response_fields(reviews)


def get_my_reviews(user_id: int) -> list[dict]:
    """사용자가 쓴 리뷰를 행사 정보와 함께 최근 수정순으로 반환한다."""

    reviews = db.session.scalars(
        select(Review)
        .where(Review.user_id == user_id)
        .order_by(
            Review.updated_at.desc(),
            Review.created_at.desc(),
            Review.id.desc()
        )
    ).all()

    if not reviews:
        return []

    # 리뷰에 포함된 행사 ID를 가져온다.
    event_ids = [review.event_id for review in reviews]

    # 리뷰에 해당하는 행사 정보를 조회한다.
    events = db.session.scalars(
        select(Event).where(Event.id.in_(event_ids))
    ).all()

    # 행사 ID로 행사 객체를 찾을 수 있도록 구성한다.
    event_map = {event.id: event for event in events}

    # 응답용 작성자(author_info)와 이미지 {key, url}(image_items)을 채운다.
    _with_response_fields(reviews)

    result = []

    for review in reviews:
        event = event_map.get(review.event_id)

        if event is None:
            raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

        result.append({
            "id": review.id,
            "user_id": review.user_id,
            "event_id": review.event_id,
            "rating": review.rating,
            "content": review.content,
            "created_at": review.created_at,
            "updated_at": review.updated_at,
            "author_info": review.author_info,
            "image_items": review.image_items,
            "event": {
                "id": event.id,
                "title": event.title,
                "image_url": event.image_url,
                "end_date": event.end_date,
            },
        })

    return result


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


def get_rating_map(event_ids) -> dict[int, dict]:
    """여러 행사의 평균 평점과 리뷰 개수를 쿼리 한 번으로 구한다. 목록 카드용이다.

    계산 규칙은 get_rating_info와 같다(소수 첫째 자리 반올림). 리뷰가 없는 행사는 결과에 없다.
    """
    ids = list(event_ids)

    if not ids:
        return {}

    rows = db.session.execute(
        select(Review.event_id, func.avg(Review.rating), func.count(Review.id))
        .where(Review.event_id.in_(ids))
        .group_by(Review.event_id)
    ).all()

    return {
        event_id: {"average_rating": round(float(average), 1), "review_count": count}
        for event_id, average, count in rows
    }


def _get_review_for_write(review_id: int) -> Review | None:
    """수정·삭제할 리뷰를 행 잠금(SELECT ... FOR UPDATE)으로 읽는다.

    같은 리뷰의 수정·삭제가 동시에 오면 뒤 요청이 앞 요청의 커밋을 기다린 뒤 최신 상태를 읽는다.
    그래서 수정끼리는 앞 수정이 반영된 images를 기준으로 비교하고(빠진 사진 정리 누락 방지),
    삭제 뒤의 수정은 0행 UPDATE(StaleDataError, 500) 대신 REVIEW_NOT_FOUND가 된다.
    populate_existing은 세션에 남은 이전 값 대신 잠금 뒤 읽은 값으로 객체를 갱신한다.
    """
    return db.session.scalar(
        select(Review)
        .where(Review.id == review_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def update_review(review_id: int, user_id: int, data: dict) -> Review:
    """본인 리뷰에서 data에 있는 rating/content/images만 수정한다. images는 목록 전체를 교체한다.

    Raises:
        BusinessException: 리뷰가 없으면 REVIEW_NOT_FOUND, 작성자가 아니면 REVIEW_FORBIDDEN,
            다른 리뷰에 이미 붙은 이미지면 REVIEW_IMAGE_ALREADY_ATTACHED,
            새로 붙이는 이미지가 직접 올린 미첨부 이미지가 아니면 REVIEW_IMAGE_NOT_UPLOADED.
    """
    review = _get_review_for_write(review_id)

    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    # 값을 바꾸기 전에 검사해, 거부될 때 세션에 일부만 바뀐 리뷰가 남지 않게 한다.
    if "images" in data:
        _ensure_images_not_attached(data["images"], review.id)
        # 이미 이 리뷰에 붙어 있던 key는 다시 확인하지 않는다.
        _claim_uploads([key for key in data["images"] if key not in (review.images or [])], user_id)

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
    _delete_unreferenced_images(removed_images)

    return _with_response_fields([review])[0]


def delete_review(review_id: int, user_id: int) -> Review:
    """본인 리뷰를 삭제하고 삭제된 리뷰를 반환한다.

    첨부 이미지 중 다른 리뷰가 참조하지 않는 것만 저장소에서 지운다. 저장소 삭제가 실패해도 로그만 남긴다.

    Raises:
        BusinessException: 리뷰가 없으면 REVIEW_NOT_FOUND, 작성자가 아니면 REVIEW_FORBIDDEN.
    """
    review = _get_review_for_write(review_id)

    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    # users.service.delete_user처럼 삭제 전에 필요한 값을 미리 꺼내 둔다. 응답용 작성자·URL도 이때 만든다.
    _with_response_fields([review])
    images = list(review.images or [])

    db.session.delete(review)
    db.session.commit()
    # update_review와 같이 커밋 성공 뒤에 저장소 파일을 지운다.
    _delete_unreferenced_images(images)

    return review