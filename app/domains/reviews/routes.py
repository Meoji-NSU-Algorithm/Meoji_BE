from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.core.response import CommonResponse
from app.domains.reviews.schemas import (
    ReviewCreateSchema,
    ReviewUpdateSchema,
    ReviewResponseSchema,
)
from app.domains.reviews import service as review_service

# Review API에서 사용하는 Blueprint를 생성한다.
#
# Blueprint는 여러 개의 API Route를 하나의 그룹으로 묶어 관리하기 위한 기능이다.
# Review 관련 API를 review_bp에 등록하면,
# 나중에 상위 API Blueprint에 한 번에 등록할 수 있다.
#
# url_prefix="/reviews"를 지정했기 때문에
# routes.py에서 작성하는 Route 앞에 "/reviews"가 자동으로 붙는다.
#
# 예시)
#   @review_bp.post("")
#   → POST /reviews
#
#   @review_bp.get("/my")
#   → GET /reviews/my
#
# 상위 Blueprint에서 "/api"를 사용하고 있다면
# 실제 요청 URL은 다음과 같이 된다.
#
#   POST /api/reviews
#   GET  /api/reviews/my
#
review_bp = Blueprint("reviews", __name__, url_prefix="/reviews")

# 아래 @review_bp.route 데코레이터가 review_bp에 각 Route를 등록한다.
# app/domains/reviews/routes.py는 이 모듈에서 review_bp를 가져와 부모에 전달한다.
# 현재 등록된 최종 경로는 다음과 같다.
#   POST   /api/reviews
#   GET    /api/reviews/event/<event_id>
#   GET    /api/reviews/event/<event_id>/rating
#   GET    /api/reviews/my
#   PUT    /api/reviews/<review_id>
#   DELETE /api/reviews/<review_id>


# 리뷰 API의 HTTP 요청과 응답을 처리하는 라우트 모듈이다.
#
# [라우트의 역할]
# - HTTP 요청을 받아 필요한 데이터를 추출한다.
# - JWT 인증을 처리하고 현재 사용자의 ID를 확인한다.
# - Schema를 사용하여 요청 데이터를 검증한다.
# - Service의 비즈니스 로직을 호출한다.
# - 처리 결과를 Schema와 CommonResponse를 사용하여
#   공통 JSON 응답 형식으로 반환한다.
#
# [사용하는 주요 함수]
# - jwt_required()
#   → API 요청에 JWT 인증이 필요한 경우 사용한다.
#
# - get_jwt_identity()
#   → JWT에 저장된 현재 사용자의 ID를 가져온다.
#
# - ReviewCreateSchema
#   → 리뷰 생성 요청 데이터를 검증한다.
#
# - ReviewUpdateSchema
#   → 리뷰 수정 요청 데이터를 검증한다.
#
# - ReviewResponseSchema
#   → Review 객체를 API 응답 형식으로 변환한다.
#
# - review_service.create_review()
#   → 새로운 리뷰를 생성한다.
#
# - review_service.get_reviews_by_event()
#   → 특정 행사의 리뷰 목록을 조회한다.
#
# - review_service.get_my_reviews()
#   → 현재 사용자가 작성한 리뷰 목록을 조회한다.
#
# - review_service.get_rating_info()
#   → 평균 평점과 리뷰 개수를 조회한다.
#
# - review_service.update_review()
#   → 리뷰를 수정한다.
#
# - review_service.delete_review()
#   → 리뷰를 삭제한다.
#
# - CommonResponse.success()
#   → API의 성공 응답을 공통 형식으로 만든다.
#
# [API 호출 공통 사항]
# - 모든 리뷰 API는 JWT 인증이 필요하다.
# - Authorization 헤더에 Access Token을 포함해야 한다.
#
# Authorization: Bearer <access_token>


# 리뷰 생성 요청을 처리하고 생성된 리뷰를 반환한다.
@review_bp.post("")
@jwt_required()
def create():
    # JWT에서 현재 로그인한 사용자의 ID를 가져온다.
    user_id = int(get_jwt_identity())

    # 요청 데이터를 Schema로 검증하고 변환한다.
    data = ReviewCreateSchema().load(request.get_json(silent=True) or {})

    # JWT에서 가져온 사용자 ID를 리뷰 데이터에 추가한다.
    data["user_id"] = user_id

    # 리뷰 생성 Service를 호출한다.
    result = review_service.create_review(data)

    # 생성된 리뷰를 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 201


# 특정 행사의 리뷰 목록 조회 요청을 처리한다.
@review_bp.get("/event/<int:event_id>")
@jwt_required()
def get_by_event(event_id):
    # 행사 ID를 기준으로 리뷰 목록을 조회한다.
    result = review_service.get_reviews_by_event(event_id)

    # 조회된 리뷰 목록을 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema(many=True).dump(result)
        )
    ), 200


# 특정 행사의 평균 평점과 리뷰 개수 조회 요청을 처리한다.
@review_bp.get("/event/<int:event_id>/rating")
@jwt_required()
def get_average_rating_by_event(event_id):
    # 행사 ID를 기준으로 평균 평점과 리뷰 개수를 조회한다.
    rating_info = review_service.get_rating_info(event_id)

    # 평점 정보를 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success({
            "event_id": event_id,
            "average_rating": rating_info["average_rating"],
            "review_count": rating_info["review_count"],
        })
    ), 200


# 현재 로그인한 사용자의 리뷰 목록 조회 요청을 처리한다.
@review_bp.get("/my")
@jwt_required()
def get_my():
    # JWT에서 현재 로그인한 사용자의 ID를 가져온다.
    user_id = int(get_jwt_identity())

    # 현재 사용자가 작성한 리뷰를 조회한다.
    result = review_service.get_my_reviews(user_id)

    # 조회된 리뷰 목록을 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema(many=True).dump(result)
        )
    ), 200


# 리뷰 수정 요청을 처리하고 수정된 리뷰를 반환한다.
@review_bp.put("/<int:review_id>")
@jwt_required()
def update(review_id):
    # JWT에서 현재 로그인한 사용자의 ID를 가져온다.
    user_id = int(get_jwt_identity())

    # 요청 데이터를 Schema로 검증하고 변환한다.
    data = ReviewUpdateSchema().load(request.get_json(silent=True) or {})

    # 리뷰 수정 Service를 호출한다.
    result = review_service.update_review(review_id, user_id, data)

    # 수정된 리뷰를 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 200


# 리뷰 삭제 요청을 처리하고 삭제된 리뷰를 반환한다.
@review_bp.delete("/<int:review_id>")
@jwt_required()
def delete(review_id):
    # JWT에서 현재 로그인한 사용자의 ID를 가져온다.
    user_id = int(get_jwt_identity())

    # 리뷰 삭제 Service를 호출한다.
    result = review_service.delete_review(review_id, user_id)

    # 삭제된 리뷰를 공통 응답 형식으로 반환한다.
    return jsonify(
        CommonResponse.success(
            ReviewResponseSchema().dump(result)
        )
    ), 200
