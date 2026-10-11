# 모든 API Blueprint를 한 곳에 모으는 "부모 Blueprint" 모듈.
#
# [Blueprint란?]
#   Flask에서 라우트(URL)들을 기능별로 묶어두는 단위. Spring의 @RequestMapping이 붙은
#   Controller 클래스 하나라고 생각하면 된다. (auth_bp = 인증 컨트롤러, users_bp = 유저 컨트롤러)
#
# [왜 부모 Blueprint로 한 번 더 묶나?]
#   - app/__init__.py(앱 팩토리)는 이 api_bp 하나만 등록하면 된다.
#     새 도메인(regions, properties 등)이 생겨도 app/__init__.py는 건드리지 않고
#     이 파일에 import 한 줄 + register 한 줄만 추가하면 된다.
#   - "/api" 접두사를 여기 한 곳에서만 관리한다. 나중에 버전을 붙이고 싶으면
#     url_prefix="/api/v1" 로 한 줄만 바꾸면 모든 API 경로에 적용된다.
#
# [최종 URL = 부모 prefix + 자식 prefix + 라우트 경로]
#   /api  +  /auth   +  /kakao    →  POST /api/auth/kakao     카카오 로그인(회원가입 포함)
#   /api  +  /auth   +  /refresh  →  POST /api/auth/refresh   토큰 재발급
#   /api  +  /auth   +  /logout   →  POST /api/auth/logout    로그아웃
#   /api  +  /users  +  /me       →  GET  /api/users/me       내 정보 조회
#   /api  +  /reviews + (없음)    →  POST /api/reviews        리뷰 작성
#   /api  +  /event  + (없음)    →  GET  /api/event          진행 중·예정 행사 목록
#   /api  +  /event  + /<id>     →  GET  /api/event/<id>     행사 상세
#   자식 Blueprint의 url_prefix에는 "/api"를 다시 쓰지 않는다.
#   중복 지정하면 /api/api/auth/... 같은 주소가 된다.
#
# [새 도메인 추가하는 법] 예: regions
#   1) app/api/regions/routes.py 에 regions_bp = Blueprint("regions", __name__, url_prefix="/regions")
#   2) app/api/regions/__init__.py 에서 regions_bp re-export
#   3) 이 파일에 아래 두 줄 추가
#        from app.api.regions import regions_bp
#        api_bp.register_blueprint(regions_bp)

from flask import Blueprint

from app.api.auth import auth_bp       # 인증 관련 API (/auth/...)
from app.api.users import users_bp     # 유저 관련 API (/users/...)
from app.api.reviews import review_bp  # 리뷰 관련 API (/reviews/...)
from app.api.events import events_bp   # 행사 조회 API (/event/...)
from app.api.directions import directions_bp  # 길찾기 API (/directions/...)

# "api"는 Blueprint 이름. url_for()로 URL을 만들 때 "api.auth.kakao_login" 처럼
# 부모 이름.자식 이름.함수명 형태의 endpoint 이름에 쓰인다.
api_bp = Blueprint("api", __name__, url_prefix="/api")


# 자식 Blueprint들을 부모에 붙인다. 등록 순서는 상관없다.
api_bp.register_blueprint(auth_bp)
api_bp.register_blueprint(users_bp)
api_bp.register_blueprint(review_bp)
api_bp.register_blueprint(events_bp)
api_bp.register_blueprint(directions_bp)
