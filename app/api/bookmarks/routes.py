from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.common_response import CommonResponse
from app.schemas.bookmark import (
    BookmarkCreateSchema,
    BookmarkListResponseSchema,
    BookmarkResponseSchema,
)
from app.services.bookmark_service import add_bookmark, get_my_bookmarks, remove_bookmark

# 기존 API 라우트와 같은 방식으로 routes.py에서 Blueprint를 정의한다.
bookmark_bp = Blueprint("bookmarks", __name__, url_prefix="/bookmarks")


@bookmark_bp.route("", methods=["POST"])
@jwt_required()
def create():
    """로그인한 사용자의 북마크를 추가한다 (신규·중복 모두 200)."""
    user_id = int(get_jwt_identity())
    # 요청 본문을 스키마로 검증한 뒤 두 입력 표기 중 전달된 행사 ID를 사용한다.
    data = BookmarkCreateSchema().load(request.get_json(silent=True) or {})
    event_id = data.get("event_id", data.get("legacy_event_id"))
    add_bookmark(user_id, event_id)
    response_data = BookmarkResponseSchema().dump(
        {"event_id": event_id, "is_bookmarked": True}
    )
    return jsonify(CommonResponse.success(response_data)), 200


@bookmark_bp.route("/my", methods=["GET"])
@jwt_required()
def get_my():
    """로그인한 사용자 본인의 북마크 목록만 반환한다."""
    user_id = int(get_jwt_identity())
    bookmarks = get_my_bookmarks(user_id)
    response_data = BookmarkListResponseSchema().dump(bookmarks)
    return jsonify(CommonResponse.success(response_data)), 200


@bookmark_bp.route("/<int:event_id>", methods=["DELETE"])
@jwt_required()
def delete(event_id):
    """로그인한 사용자의 특정 행사 북마크를 해제한다."""
    user_id = int(get_jwt_identity())
    result = remove_bookmark(user_id, event_id)
    response_data = BookmarkResponseSchema().dump(result)
    return jsonify(CommonResponse.success(response_data)), 200
