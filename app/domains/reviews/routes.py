"""리뷰 API 라우트(`/api/reviews`).

모든 엔드포인트는 JWT가 필요하다. 행사 상세(`/api/events/<id>`)에는 해당 행사의 리뷰가 함께 내려간다.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.core.response import CommonResponse
from app.domains.reviews.schemas import (
    ReviewCreateSchema,
    ReviewUpdateSchema,
    ReviewResponseSchema,
    EventRatingResponseSchema,
    ReviewImageResponseSchema,
)
from app.domains.reviews import service as review_service

# 부모 Blueprint(api_bp)가 /api를 붙인다.
review_bp = Blueprint("reviews", __name__, url_prefix="/reviews")


@review_bp.post("")
@jwt_required()
def create_review():
    """리뷰를 작성한다.

    POST /api/reviews. 본문: event_id, rating, content. 성공 시 201과 생성된 리뷰.

    Raises:
        COMMON_INVALID_INPUT: 본문 검증 실패(400).
        USER_NOT_FOUND / EVENT_NOT_FOUND: 작성자 또는 행사가 없음(404).
    """
    user_id = int(get_jwt_identity())

    data = ReviewCreateSchema().load(request.get_json(silent=True) or {})

    # 작성자는 본문이 아니라 JWT 기준으로만 정한다.
    data["user_id"] = user_id

    result = review_service.create_review(data)

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
    """본인이 쓴 리뷰의 평점 또는 내용을 수정한다.

    PUT /api/reviews/<review_id>. 본문: rating, content 중 하나 이상. 성공 시 200.

    Raises:
        COMMON_INVALID_INPUT: 본문 검증 실패 또는 수정할 값 없음(400).
        REVIEW_NOT_FOUND: 리뷰가 없음(404).
        REVIEW_FORBIDDEN: 작성자가 아님(403).
    """
    user_id = int(get_jwt_identity())

    data = ReviewUpdateSchema().load(request.get_json(silent=True) or {})

    result = review_service.update_review(review_id, user_id, data)

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



@review_bp.post("/images")
@jwt_required()
def upload_image():
    """리뷰에 붙일 이미지를 한 장 올리고 저장소 key와 url을 반환한다.

    POST /api/reviews/images. multipart/form-data의 image 필드. 성공 시 201.
    받은 key를 리뷰 작성(POST)·수정(PUT) 본문의 images에 넣어 연결한다.
    원본은 저장하지 않고 webp로 변환한 결과만 저장한다(app/domains/reviews/images.py).

    Raises:
        COMMON_INVALID_INPUT: image 필드가 없음(400).
        REVIEW_IMAGE_INVALID: 이미지가 아니거나 지원하지 않는 형식(400).
        REVIEW_IMAGE_TOO_LARGE: 원본이 10MB 초과(413).
        REVIEW_IMAGE_STORAGE_UNAVAILABLE: 저장소 설정 누락 또는 통신 실패(503).
    """
    key = review_service.upload_image(request.files.get("image"))

    return jsonify(
        CommonResponse.success(
            ReviewImageResponseSchema().dump({"key": key})
        )
    ), 201
