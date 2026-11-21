"""북마크 API 라우트(`/api/bookmarks`).

모든 엔드포인트는 JWT가 필요하며, 로그인한 사용자 본인의 북마크만 다룬다.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.core.response import CommonResponse
from app.domains.bookmarks import service as bookmark_service
from app.domains.bookmarks.schemas import (
    BookmarkCreateSchema,
    BookmarkListResponseSchema,
    BookmarkResponseSchema,
)

# 부모 Blueprint(api_bp)가 /api를 붙인다.
bookmark_bp = Blueprint("bookmarks", __name__, url_prefix="/bookmarks")


@bookmark_bp.post("")
@jwt_required()
def create_bookmark():
    """북마크를 추가한다.

    POST /api/bookmarks. 본문: eventId(기존 event_id도 허용, 둘 중 하나만).
    새로 만들면 201, 이미 있으면 200(멱등).

    Raises:
        COMMON_INVALID_INPUT: 본문 검증 실패(400).
        USER_NOT_FOUND / EVENT_NOT_FOUND: 회원 또는 행사가 없음(404).
    """
    user_id = int(get_jwt_identity())

    # 요청 본문을 스키마로 검증한 뒤 두 입력 표기 중 전달된 행사 ID를 사용한다.
    data = BookmarkCreateSchema().load(request.get_json(silent=True) or {})
    event_id = data.get("event_id", data.get("legacy_event_id"))

    _, created = bookmark_service.add_bookmark(user_id, event_id)

    response_data = BookmarkResponseSchema().dump(
        {"event_id": event_id, "is_bookmarked": True}
    )
    return jsonify(CommonResponse.success(response_data)), 201 if created else 200


@bookmark_bp.get("")
@jwt_required()
def list_my_bookmarks():
    """내 북마크 목록을 최근 저장 순으로 반환한다.

    GET /api/bookmarks. 본인 북마크만 내려간다.

    Raises:
        USER_NOT_FOUND: 회원이 없음(404).
    """
    user_id = int(get_jwt_identity())

    bookmarks = bookmark_service.get_my_bookmarks(user_id)

    response_data = BookmarkListResponseSchema().dump(bookmarks)
    return jsonify(CommonResponse.success(response_data)), 200


@bookmark_bp.delete("/<int:event_id>")
@jwt_required()
def delete_bookmark(event_id):
    """특정 행사의 북마크를 해제한다.

    DELETE /api/bookmarks/<event_id>. 이미 해제된 경우에도 200(멱등).

    Raises:
        USER_NOT_FOUND: 회원이 없음(404).
    """
    user_id = int(get_jwt_identity())

    result = bookmark_service.remove_bookmark(user_id, event_id)

    response_data = BookmarkResponseSchema().dump(result)
    return jsonify(CommonResponse.success(response_data)), 200
