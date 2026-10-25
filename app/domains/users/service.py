# 유저(User) 조회/생성만 담당하는 서비스.
# JWT나 카카오 통신은 전혀 모른다. "우리 DB의 user 테이블"만 다룬다.
# 카카오 로그인 흐름에서는 auth_service가, 내 정보 조회에서는 users 라우트가 이 파일을 호출한다.
from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.users.models import User


# PyCharm 오탐 경고 끄기: User(kakao_id=..., ...)에 "예기치 않은 인수" 경고가 뜨지만 코드는 정상이다.
#   오탐(false positive) = 문제가 없는데 검사 도구가 문제가 있다고 잘못 탐지한 것.
#   SQLAlchemy 모델의 생성자는 "컬럼 이름을 키워드 인자로 받도록" 실행 시점에 자동으로 만들어지는데,
#   PyCharm은 코드를 실행하지 않고 읽기만 하므로 그 생성자를 못 보고 "인자를 받지 않는 생성자"로 착각한다.
#   아래 주석은 이 함수 안에서만 "함수 호출 인자 검사"를 끄는 PyCharm 전용 표시이며, 실행에는 영향이 없다.
# noinspection PyArgumentList
def get_or_create_kakao_user(info: dict) -> tuple[User, bool]:
    """카카오 사용자 정보로 유저를 찾고, 없으면 만든다. (유저, 신규여부)를 반환한다.

    info: kakao_auth_service.get_kakao_user_info()의 반환값
          {"kakao_id": int, "email": str, "nickname": str, "profile_image": str | None}

    반환값 예: (User 객체, True)  → 이번에 회원가입됨
              (User 객체, False) → 기존 회원 로그인
    """
    # 유저를 kakao_id(카카오 회원번호)로 찾는 이유:
    #   이메일은 사용자가 카카오 계정에서 바꿀 수 있지만, kakao_id는 절대 바뀌지 않는 고유값이다.
    #   이메일로 찾으면 이메일을 바꾼 기존 회원을 신규 회원으로 착각할 수 있다.
    #
    # SQLAlchemy 2.x 쿼리 문법:
    #   db.select(User)              → SELECT * FROM user
    #   .filter_by(kakao_id=...)     → WHERE kakao_id = ...
    #   db.session.scalar(...)       → 결과 첫 번째 행을 User 객체로 반환, 없으면 None
    #   (예전 방식 User.query.filter_by(...).first() 와 같은 동작. User.query는 legacy API라 사용하지 않는다)
    user = db.session.scalar(db.select(User).filter_by(kakao_id=info["kakao_id"]))
    is_new_user = user is None

    if is_new_user:
        # 처음 온 사용자 → 회원가입. created_at/updated_at은 모델의 default로 자동으로 채워진다.
        user = User(
            kakao_id=info["kakao_id"],
            email=info["email"],
            nickname=info["nickname"],
            profile_image=info["profile_image"],
        )
        # add()는 "저장할 목록에 올려두기"만 한다. 실제 INSERT는 아래 commit() 때 실행된다.
        db.session.add(user)
    else:
        # 기존 회원 → 카카오에서 닉네임/프로필 사진을 바꿨을 수 있으니 최신 값으로 갱신한다.
        # 이미 세션이 관리 중인 객체라서 add() 없이 값만 바꿔도 commit() 때 UPDATE된다.
        # updated_at은 모델의 onupdate 설정으로 자동 갱신된다.
        # (이메일은 현재 정책상 가입 시점의 값을 그대로 사용하고, 로그인 때 갱신하지 않는다)
        user.nickname = info["nickname"]
        user.profile_image = info["profile_image"]

    # 신규/기존 둘 다 여기서 한 번에 DB에 반영한다.
    # commit() 이후에는 신규 유저도 user.id(PK)가 채워져 있어서 바로 토큰 발급에 쓸 수 있다.
    db.session.commit()
    return user, is_new_user


def get_user(user_id: int) -> User:
    """id로 유저를 조회한다. 없으면(탈퇴 등) USER_NOT_FOUND.

    토큰의 sub(유저 id)로 유저를 찾을 때 사용한다. (/api/users/me, /api/auth/refresh)
    토큰은 서명만 맞으면 유효하기 때문에, 유저가 탈퇴한 뒤에도 토큰은 살아 있을 수 있다.
    그래서 토큰만 믿지 않고 실제 DB에 유저가 있는지 확인한다.
    """
    # db.session.get(모델, PK): 기본키로 한 건 조회. 없으면 None. (SQLAlchemy 2.x 방식)
    user = db.session.get(User, user_id)
    if user is None:
        # 전역 핸들러(app/__init__.py)가 404 + {"code": "USER_NOT_FOUND", ...} 응답으로 바꿔준다.
        raise BusinessException(ErrorCode.USER_NOT_FOUND)
    return user
