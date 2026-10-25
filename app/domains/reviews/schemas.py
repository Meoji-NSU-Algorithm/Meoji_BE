from marshmallow import (
    Schema,
    fields,
    validate,
    validates_schema,
    ValidationError,
)


# 리뷰 API의 요청 및 응답 데이터 형식을 정의하는 Schema 모듈이다.
#
# [Schema의 역할]
# - API 요청 데이터의 필드와 타입을 정의한다.
# - 리뷰 생성 및 수정 요청값을 검증한다.
# - 잘못된 요청값이 전달되면 ValidationError를 발생시킨다.
# - DB의 Review 객체를 API 응답 형식으로 변환한다.
#
# [Schema와 다른 계층의 역할]
#
# - routes.py
#   · HTTP 요청 수신
#   · JWT 인증
#   · Schema를 통한 요청값 검증
#   · Service 호출
#   · API 응답 반환
#
# - Schema
#   · 요청 데이터의 형식 및 입력값 검증
#   · 응답 데이터의 형식 정의
#
# - review_service.py
#   · DB 조회 및 변경
#   · 리뷰 생성, 조회, 수정, 삭제
#   · 작성자 권한 확인
#   · 평균 평점 계산
#
# [주요 Schema]
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
# [평점 검증]
# 리뷰 평점은 0.5 ~ 5.0 범위에서
# 0.5 단위로만 입력할 수 있다.
#
# 예:
#   0.5, 1.0, 1.5, 2.0, ... , 4.5, 5.0
#
# 잘못된 값:
#   0.4, 1.2, 3.7, 5.5


# 평점 입력값을 검증한다.
#
# 검증 조건:
# - 0.5점 이상 5점 이하
# - 0.5점 단위로 입력
#
# ReviewCreateSchema와 ReviewUpdateSchema에서
# rating 필드의 validate 옵션으로 사용한다.

# 리뷰 평점의 범위와 입력 단위를 검증한다.
def validate_rating(value):
    # 평점이 0.5 이상 5 이하인지 확인한다.
    if value < 0.5 or value > 5:
        raise ValidationError()

    # 평점이 0.5 단위인지 확인한다.
    if value * 2 != int(value * 2):
        raise ValidationError()


# 리뷰 생성 요청에 필요한 필드와 검증 조건을 정의한다.
class ReviewCreateSchema(Schema):

    # 리뷰가 작성될 행사 ID를 받는다.
    event_id = fields.Integer(required=True)

    # 0.5 ~ 5.0 범위의 평점을 받는다.
    rating = fields.Float(required=True, validate=validate_rating)

    # 최소 1글자 이상의 리뷰 내용을 받는다.
    content = fields.String(required=True, validate=validate.Length(min=1))


# 리뷰 수정 요청에 필요한 필드와 검증 조건을 정의한다.
class ReviewUpdateSchema(Schema):

    # 전달된 경우 평점의 범위와 단위를 검증한다.
    rating = fields.Float(required=False, validate=validate_rating)

    # 전달된 경우 리뷰 내용이 비어 있지 않은지 검증한다.
    content = fields.String(required=False, validate=validate.Length(min=1))

    # 수정할 데이터가 하나 이상 전달되었는지 확인한다.
    @validates_schema
    def validate_update(self, data, **kwargs):
        # 수정할 데이터가 없으면 오류를 발생시킨다.
        if not data:
            raise ValidationError()


# Review 객체의 API 응답 형식을 정의한다.
class ReviewResponseSchema(Schema):

    # 리뷰의 고유 ID를 반환한다.
    id = fields.Integer()

    # 리뷰 작성자의 ID를 반환한다.
    user_id = fields.Integer()

    # 리뷰가 작성된 행사 ID를 반환한다.
    event_id = fields.Integer()

    # 리뷰 평점을 반환한다.
    rating = fields.Float()

    # 리뷰 내용을 반환한다.
    content = fields.String()

    # 리뷰 생성 시간을 반환한다.
    created_at = fields.DateTime()

    # 리뷰 수정 시간을 반환한다.
    updated_at = fields.DateTime()