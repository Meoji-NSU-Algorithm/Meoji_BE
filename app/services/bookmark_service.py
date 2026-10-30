from sqlalchemy.exc import IntegrityError

from app.errors import BusinessException, ErrorCode
from app.extensions import db
from app.models.bookmark import Bookmark
from app.models.tour_content import Event
from app.models.user import User


def _require_user(user_id):
    if db.session.get(User, user_id) is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)


def add_bookmark(user_id, event_id):
    """북마크를 멱등하게 추가하고 새로 생성했는지 반환한다."""
    _require_user(user_id)
    if db.session.get(Event, event_id) is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    existing = Bookmark.query.filter_by(user_id=user_id, event_id=event_id).first()
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
        existing = Bookmark.query.filter_by(user_id=user_id, event_id=event_id).first()
        if existing is not None:
            return existing, False
        raise


def get_my_bookmarks(user_id):
    """사용자의 북마크 행사를 최근 저장 순으로 반환한다."""
    _require_user(user_id)
    rows = (
        db.session.query(Bookmark, Event)
        .join(Event, Bookmark.event_id == Event.id)
        .filter(Bookmark.user_id == user_id)
        .order_by(Bookmark.created_at.desc(), Bookmark.id.desc())
        .all()
    )
    events = [
        {
            "id": event.id,
            "title": event.title,
            "image_url": event.thumbnail_url or event.image_url,
            "start_date": event.start_date,
            "end_date": event.end_date,
            "price_type": ("FREE" if event.is_free is True else "PAID" if event.is_free is False else "UNKNOWN"),
        }
        for _, event in rows
    ]
    return {"total_count": len(events), "events": events}


def remove_bookmark(user_id, event_id):
    """북마크를 해제하며 이미 해제된 경우에도 같은 성공 응답을 반환한다."""
    _require_user(user_id)
    bookmark = Bookmark.query.filter_by(user_id=user_id, event_id=event_id).first()
    if bookmark is not None:
        db.session.delete(bookmark)
        db.session.commit()
    return {"event_id": event_id, "is_bookmarked": False}
