"""유저 조회/생성을 담당하는 서비스. JWT와 카카오 통신은 모르고 user 테이블만 다룬다."""
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.users.models import User


# SQLAlchemy 모델 생성자는 실행 시점에 만들어져 PyCharm이 인식하지 못해 나는 오탐을 끈다.
# noinspection PyArgumentList
def get_or_create_kakao_user(info: dict) -> tuple[User, bool]:
    """카카오 사용자 정보로 유저를 찾고, 없으면 가입시킨다.

    Args:
        info: kakao_client.get_kakao_user_info()의 반환값.

    Returns:
        (유저, 신규 가입 여부)

    Raises:
        BusinessException: 같은 이메일을 다른 카카오 계정이 이미 쓰면 USER_EMAIL_CONFLICT.
    """
    # 이메일은 카카오 계정에서 바뀔 수 있어 바뀌지 않는 kakao_id로 찾는다.
    # 이메일로 찾으면 이메일을 바꾼 기존 회원이 신규 회원으로 처리된다.
    user = db.session.scalar(db.select(User).filter_by(kakao_id=info["kakao_id"]))
    is_new_user = user is None

    if is_new_user:
        user = User(
            kakao_id=info["kakao_id"],
            email=info["email"],
            nickname=info["nickname"],
            profile_image=info["profile_image"],
        )
        db.session.add(user)
    else:
        # 닉네임과 프로필 사진은 로그인 때마다 최신 값으로 갱신한다.
        # 이메일은 가입 시점의 값을 유지한다.
        user.nickname = info["nickname"]
        user.profile_image = info["profile_image"]

    # commit 이후에는 신규 유저도 user.id가 채워져 바로 토큰 발급에 쓸 수 있다.
    try:
        db.session.commit()
    except IntegrityError:
        # 같은 kakao_id의 동시 가입 또는 이메일 unique 충돌
        db.session.rollback()
        user = db.session.scalar(db.select(User).filter_by(kakao_id=info["kakao_id"]))
        if user is None:
            # kakao_id로 못 찾으면 다른 계정이 같은 이메일을 쓰는 것이다.
            raise BusinessException(ErrorCode.USER_EMAIL_CONFLICT)
        return user, False
    return user, is_new_user


def get_user(user_id: int) -> User:
    """id로 유저를 조회한다.

    토큰은 서명만 맞으면 유효하므로, 유저가 탈퇴한 뒤에도 살아 있을 수 있다. 그래서 DB에서 다시 확인한다.

    Raises:
        BusinessException: 유저가 없으면 USER_NOT_FOUND.
    """
    user = db.session.get(User, user_id)
    if user is None:
        raise BusinessException(ErrorCode.USER_NOT_FOUND)
    return user
