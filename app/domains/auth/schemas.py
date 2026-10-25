# 인증(auth) API의 요청/응답 형식을 정의하는 marshmallow 스키마 모음.
# (Spring의 Request/Response DTO + @Valid 역할)
#
# [스키마의 두 가지 용도]
#   - load(dict) : "요청 검증". 프론트가 보낸 body가 규칙에 맞는지 검사하고, 통과하면 dict를 반환한다.
#                  규칙 위반이면 ValidationError를 던지고 → app/__init__.py 핸들러가 400 응답을 만든다.
#                  예) {"success": false, "code": "COMMON_INVALID_INPUT", "message": "요청 값이 올바르지 않습니다.",
#                       "errors": {"code": ["Missing data for required field."]}}
#   - dump(obj)  : "응답 직렬화". 파이썬 dict/객체에서 스키마에 적힌 필드만 골라 응답용 dict로 만든다.
#
# [`# noinspection PyArgumentList` 주석은 뭔가? → PyCharm 오탐 경고 끄기]
#   오탐(誤探, false positive) = "문제가 없는데 문제가 있다고 잘못 탐지한 것".
#   화재경보기가 연기가 없는데 울리는 것과 같다. 코드는 정상인데 검사 도구(PyCharm)가 착각해서 경고를 띄운 경우다.
#
#   여기서는 validate.Length(min=1)에 "매개변수 'value'이(가) 채워지지 않았습니다" 경고가 뜬다.
#   PyCharm이 Length의 생성자 Length(min, max, equal, error)를 부모 클래스 Validator의
#   __call__(value) 메서드와 헷갈려서 "value 인자가 빠졌다"고 잘못 판단한 것이다.
#   실제로 실행해 보면 빈 값/누락 검증이 정상 동작한다. (우리 코드로는 고칠 수 없는 PyCharm 쪽 문제)
#
#   그래서 클래스 바로 위에 `# noinspection PyArgumentList`를 달아, 그 클래스 안에서만
#   "함수 호출 인자 검사(PyArgumentList)"를 끈다. 실행에는 아무 영향이 없는 PyCharm 전용 주석이다.
#   ※ 파일 전체나 PyCharm 설정에서 끄지 않는 이유: 이 검사는 진짜 인자 실수(오타, 개수 틀림)도
#     잡아주는 유용한 검사라서, 오탐이 나는 곳에만 좁게 끄는 게 안전하다.
from marshmallow import Schema, fields, validate

# noinspection PyArgumentList
class KakaoLoginRequestSchema(Schema):
    """POST /api/auth/kakao 요청 body 검증용. 예: {"code": "카카오 인가 코드"}"""
    # required=True: 키가 없으면 검증 실패
    # validate.Length(min=1): "" 같은 빈 문자열도 실패
    code = fields.String(required=True, validate=validate.Length(min=1))

# noinspection PyArgumentList
class LogoutRequestSchema(Schema):
    """POST /api/auth/logout 요청 body 검증용. 예: {"refresh_token": "eyJ..."}"""
    # 로그아웃 시 access(헤더)와 함께 폐기할 refresh 토큰 (body로 받음)
    refresh_token = fields.String(required=True, validate=validate.Length(min=1))

class TokenResponseSchema(Schema):
    """토큰 응답용. 로그인(/kakao)과 재발급(/refresh) 응답에서 같이 쓴다.

    dump 할 때 넘긴 dict에 없는 키는 결과에서 자동으로 빠진다.
      - 로그인   : {"access_token", "refresh_token", "is_new_user"} 세 개 모두 나감
      - 재발급   : is_new_user가 없으므로 {"access_token", "refresh_token"} 두 개만 나감
    """
    access_token = fields.String()   # API 호출용 토큰 (1시간)
    refresh_token = fields.String()  # 재발급용 토큰 (14일)
    is_new_user = fields.Boolean()   # 이번 로그인에서 회원가입이 일어났는지 (프론트 온보딩 분기용)
