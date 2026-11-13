"""북마크 추가·목록 조회·해제를 담당한다.

추가와 해제는 여러 번 호출해도 같은 결과가 나오게(멱등) 처리하며, 실패는 BusinessException으로 올린다.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.bookmarks.models import Bookmark
from app.domains.events.models import Event
from app.domains.users.models import User


def _require_user(user_id: int) -> None:
    """회원이 존재하는지 확인한다. 탈퇴 등으로 없으면 USER_NOT_FOUND를 올린다."""
    if db.session.get(User, user_id) is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)


def _find_bookmark(user_id: int, event_id: int) -> Bookmark | None:
    """사용자가 해당 행사를 북마크한 행을 찾는다. 없으면 None."""
    return db.session.scalar(
        select(Bookmark).where(Bookmark.user_id == user_id, Bookmark.event_id == event_id)
    )


def add_bookmark(user_id: int, event_id: int) -> tuple[Bookmark, bool]:
    """북마크를 멱등하게 추가하고 (북마크, 새로 생성했는지)를 반환한다.

    Raises:
        BusinessException: 회원이 없으면 USER_NOT_FOUND, 행사가 없으면 EVENT_NOT_FOUND.
    """
    _require_user(user_id)
    if db.session.get(Event, event_id) is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    existing = _find_bookmark(user_id, event_id)
    if existing is not None:
        return existing, False

    bookmark = Bookmark(user_id=user_id, event_id=event_id)
    db.session.add(bookmark)
    try:
        db.session.commit()
        return bookmark, True
    except IntegrityError:
        # 동시에 들어온 다른 요청이 먼저 저장했을 수 있어 기존 행을 다시 조회한다.
        db.session.rollback()
        existing = _find_bookmark(user_id, event_id)
        if existing is not None:
            return existing, False
        raise


def get_my_bookmarks(user_id: int) -> dict:
    """사용자의 북마크 행사를 최근 저장 순으로 반환한다.

    Returns:
        total_count와 events(id, title, image_url, start_date, end_date, price_type) 목록.

    Raises:
        BusinessException: 회원이 없으면 USER_NOT_FOUND.
    """
    _require_user(user_id)
    rows = db.session.execute(
        select(Bookmark, Event)
        .join(Event, Bookmark.event_id == Event.id)
        .where(Bookmark.user_id == user_id)
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
    ).all()
    events = [
        {
            "id": event.id,
            "title": event.title,
            "image_url": event.image_url,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "price_type": ("FREE" if event.is_free is True else "PAID" if event.is_free is False else "UNKNOWN"),
        }
        for _, event in rows
    ]
    return {"total_count": len(events), "events": events}


def remove_bookmark(user_id: int, event_id: int) -> dict:
    """북마크를 해제하며 이미 해제된 경우에도 같은 성공 결과를 반환한다.

    Raises:
        BusinessException: 회원이 없으면 USER_NOT_FOUND.
    """
    _require_user(user_id)
    bookmark = _find_bookmark(user_id, event_id)
    if bookmark is not None:
        db.session.delete(bookmark)
        db.session.commit()
    return {"event_id": event_id, "is_bookmarked": False}
