"""리뷰 API 라우트(`/api/reviews`).

모든 엔드포인트는 JWT가 필요하다. 행사 상세(`/api/events/<id>`)에는 해당 행사의 리뷰가 함께 내려간다.
"""

import json

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.core.response import CommonResponse
from app.domains.reviews.schemas import (
    ReviewCreateSchema,
    ReviewUpdateSchema,
    ReviewResponseSchema,
    EventRatingResponseSchema,
)
from app.domains.reviews import service as review_service

# 부모 Blueprint(api_bp)가 /api를 붙인다.
review_bp = Blueprint("reviews", __name__, url_prefix="/reviews")


def _body_and_files():
    """요청 본문(dict)과 사진 파일 목록을 꺼낸다.

    사진이 없으면 JSON 본문. 사진이 있으면 multipart/form-data로 본문은 data 필드(JSON 문자열)에,
    사진은 images 필드(여러 개)에 담는다. 깨진 JSON은 빈 본문으로 보고 스키마가 거부하게 둔다.
    """
    if request.mimetype != "multipart/form-data":
        return request.get_json(silent=True) or {}, []

    try:
        body = json.loads(request.form.get("data") or "{}")
    except ValueError:
        body = {}

    return body, [file for file in request.files.getlist("images") if file.filename]


@review_bp.post("")
@jwt_required()
def create_review():
    """리뷰를 작성한다.

    POST /api/reviews. 본문: event_id, rating, content. 사진은 _body_and_files 형식으로 최대 5장.
    성공 시 201과 생성된 리뷰.

    Raises:
        COMMON_INVALID_INPUT: 본문 검증 실패, 사진 5장 초과(400).
        USER_NOT_FOUND / EVENT_NOT_FOUND: 작성자 또는 행사가 없음(404).
        REVIEW_IMAGE_INVALID / REVIEW_IMAGE_TOO_LARGE: 이미지가 아니거나 한 장 10MB 초과(400/413).
        COMMON_PAYLOAD_TOO_LARGE: 요청 본문이 MAX_CONTENT_LENGTH 초과(413).
        REVIEW_IMAGE_STORAGE_UNAVAILABLE: 저장소 설정 누락 또는 통신 실패(503).
    """
    user_id = int(get_jwt_identity())

    body, files = _body_and_files()
    data = ReviewCreateSchema().load(body)

    # 작성자는 본문이 아니라 JWT 기준으로만 정한다.
    data["user_id"] = user_id

    result = review_service.create_review(data, files)

    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 201


@review_bp.get("/event/<int:event_id>")
@jwt_required()
def list_event_reviews(event_id):
    """행사의 리뷰 목록을 최근 수정순으로 반환한다.

    GET /api/reviews/event/<event_id>. JWT 필요. 리뷰가 없거나 행사가 없어도 200과 빈 목록.
    """
    result = review_service.get_reviews_by_event(event_id)

    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema(many=True).dump(result)
        )
    ), 200


@review_bp.get("/event/<int:event_id>/rating")
@jwt_required()
def get_event_rating(event_id):
    """행사의 평균 평점과 리뷰 개수를 반환한다.

    GET /api/reviews/event/<event_id>/rating. JWT 필요. 리뷰가 없거나 행사가 없으면 평점 0, 개수 0.
    """
    rating_info = review_service.get_rating_info(event_id)

    return jsonify(
        CommonResponse.success(
            EventRatingResponseSchema().dump({
                "event_id": event_id,
                "average_rating": rating_info["average_rating"],
                "review_count": rating_info["review_count"],
            })
        )
    ), 200


@review_bp.get("/my")
@jwt_required()
def list_my_reviews():
    """로그인한 사용자가 쓴 리뷰를 최근 수정순으로 반환한다.

    GET /api/reviews/my. 성공 시 200, 리뷰가 없으면 빈 목록.
    """
    user_id = int(get_jwt_identity())

    result = review_service.get_my_reviews(user_id)

    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema(many=True).dump(result)
        )
    ), 200


@review_bp.put("/<int:review_id>")
@jwt_required()
def update_review(review_id):
    """본인이 쓴 리뷰의 평점, 내용, 사진을 수정한다.

    PUT /api/reviews/<review_id>. 본문: rating, content, images(남길 기존 사진 key) 중 하나 이상,
    또는 새 사진(_body_and_files 형식). images를 빼면 기존 사진은 모두 남는다. 성공 시 200.

    Raises:
        COMMON_INVALID_INPUT: 본문 검증 실패, 수정할 값 없음, 이 리뷰에 없는 key, 사진 5장 초과(400).
        REVIEW_NOT_FOUND: 리뷰가 없음(404).
        REVIEW_FORBIDDEN: 작성자가 아님(403).
        사진 오류는 create_review와 같다.
    """
    user_id = int(get_jwt_identity())

    body, files = _body_and_files()
    # 새 사진만 보내는 요청은 본문이 비어도 된다.
    data = ReviewUpdateSchema().load(body) if body or not files else {}

    result = review_service.update_review(review_id, user_id, data, files)

    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 200


@review_bp.delete("/<int:review_id>")
@jwt_required()
def delete_review(review_id):
    """본인이 쓴 리뷰를 삭제하고 삭제된 리뷰를 반환한다.

    DELETE /api/reviews/<review_id>. 성공 시 200.

    Raises:
        REVIEW_NOT_FOUND: 리뷰가 없음(404).
        REVIEW_FORBIDDEN: 작성자가 아님(403).
    """
    user_id = int(get_jwt_identity())

    result = review_service.delete_review(review_id, user_id)

    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 200
