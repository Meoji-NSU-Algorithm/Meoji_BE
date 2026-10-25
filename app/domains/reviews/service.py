from app.core.extensions import db
from app.domains.events.models import Event
from app.domains.reviews.models import Review
from app.domains.users.models import User
from app.core.errors import BusinessException, ErrorCode
from sqlalchemy import func


# 리뷰 API의 비즈니스 로직을 담당하는 서비스 모듈이다.
#
# [서비스의 책임]
# API 계층(routes.py)에서 전달받은 검증된 데이터를 바탕으로
# 리뷰의 생성, 조회, 수정, 삭제 및 평점 집계를 처리한다.
#
# [API 계층과 서비스 계층의 역할]
#
# - API 계층
#   · JWT Access Token 인증
#   · 현재 로그인한 사용자의 user_id 확인
#   · 요청 데이터 검증(Schema)
#   · 서비스 호출
#   · 응답 데이터 변환
#
# - 서비스 계층
#   · DB 조회 및 변경
#   · 리뷰 관련 비즈니스 로직 처리
#   · 리뷰 작성자 권한 확인
#   · 평균 평점 및 리뷰 개수 계산
#
# JWT 자체는 서비스 계층에서 처리하지 않는다.
# API 계층에서 JWT의 identity를 통해 현재 사용자의 user_id를 가져온 뒤
# 필요한 서비스 함수에 전달한다.
#
# [예외 처리]
# 서비스에서 발생하는 비즈니스 예외는 BusinessException으로 발생시킨다.
# 전역 예외 처리기가 해당 예외를 처리하여
# ErrorCode에 정의된 상태 코드와 메시지를 공통 응답 형식으로 반환한다.
#
# 주요 비즈니스 예외:
#
# - REVIEW_NOT_FOUND (404)
#   → 요청한 리뷰가 존재하지 않는 경우
#
# - REVIEW_FORBIDDEN (403)
#   → 현재 로그인한 사용자가 해당 리뷰의 작성자가 아닌 경우
#
# [리뷰 작성자 권한 확인]
# 리뷰 수정 및 삭제 시
# JWT에서 전달받은 현재 사용자의 user_id와
# 리뷰에 저장된 user_id를 비교한다.
#
# 두 ID가 일치하는 경우에만 수정 또는 삭제를 허용한다.


# 새로운 리뷰를 생성한다.
def create_review(data):
    # 리뷰 작성자의 존재 여부를 확인한다.
    user = User.query.get(data["user_id"])

    # 존재하지 않는 사용자라면 예외를 발생시킨다.
    if user is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)

    # 리뷰가 작성될 행사의 존재 여부를 확인한다.
    event = Event.query.get(data["event_id"])

    # 존재하지 않는 행사라면 예외를 발생시킨다.
    if event is None:
        raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

    # 전달받은 데이터로 리뷰 객체를 생성한다.
    review = Review(
        user_id=data["user_id"],
        event_id=data["event_id"],
        rating=data["rating"],
        content=data["content"],
    )

    # 리뷰를 DB에 추가하고 저장한다.
    db.session.add(review)
    db.session.commit()

    return review


# 특정 행사의 리뷰 목록을 조회한다.
def get_reviews_by_event(event_id):
    # 행사 ID를 기준으로 리뷰를 조회하고 최근 수정순으로 정렬한다.
    reviews = Review.query.filter_by(event_id=event_id).order_by(
        Review.updated_at.desc(),
        Review.created_at.desc(),
    ).all()

    return reviews


# 현재 사용자가 작성한 리뷰 목록을 조회한다.
def get_my_reviews(user_id):
    # 사용자 ID를 기준으로 작성한 리뷰를 조회한다.
    reviews = Review.query.filter_by(user_id=user_id).all()

    return reviews


# 특정 행사의 평균 평점과 리뷰 개수를 조회한다.
def get_rating_info(event_id):
    # 행사 ID를 기준으로 평균 평점과 리뷰 개수를 조회한다.
    result = db.session.query(
        func.avg(Review.rating),
        func.count(Review.id)
    ).filter(Review.event_id == event_id).first()

    # 조회 결과에서 평균 평점과 리뷰 개수를 가져온다.
    average_rating = result[0]
    review_count = result[1]

    # 리뷰가 없으면 평균 평점을 0으로 반환한다.
    if average_rating is None:
        average_rating = 0
    else:
        # 평균 평점을 소수점 첫째 자리까지 반올림한다.
        average_rating = round(float(average_rating), 1)

    return {
        "average_rating": average_rating,
        "review_count": review_count,
    }


# 본인이 작성한 리뷰를 수정한다.
def update_review(review_id, user_id, data):
    # 리뷰 ID로 리뷰를 조회한다.
    review = Review.query.get(review_id)

    # 리뷰가 존재하지 않으면 예외를 발생시킨다.
    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    # 현재 사용자가 리뷰 작성자인지 확인한다.
    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    # 전달된 평점이 있으면 수정한다.
    if "rating" in data:
        review.rating = data["rating"]

    # 전달된 리뷰 내용이 있으면 수정한다.
    if "content" in data:
        review.content = data["content"]

    # 변경사항을 DB에 반영한다.
    db.session.commit()

    return review


# 본인이 작성한 리뷰를 삭제한다.
def delete_review(review_id, user_id):
    # 리뷰 ID로 리뷰를 조회한다.
    review = Review.query.get(review_id)

    # 리뷰가 존재하지 않으면 예외를 발생시킨다.
    if review is None:
        raise BusinessException(ErrorCode.REVIEW_NOT_FOUND)

    # 현재 사용자가 리뷰 작성자인지 확인한다.
    if review.user_id != user_id:
        raise BusinessException(ErrorCode.REVIEW_FORBIDDEN)

    # 리뷰를 DB에서 삭제한다.
    db.session.delete(review)
    db.session.commit()

    return review