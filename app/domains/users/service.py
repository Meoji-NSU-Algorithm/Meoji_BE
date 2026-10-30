"""유저 조회/생성/삭제와 약관 동의를 담당하는 서비스. JWT와 카카오 통신은 모르고 user 테이블만 다룬다."""
from datetime import datetime, timezone

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


def save_consent(user_id: int, data: dict) -> User:
    """약관 동의를 저장한다.

    필수 약관은 처음 동의한 시각을 유지하고, 다시 동의해도 덮어쓰지 않는다.
    마케팅 수신은 값이 바뀔 때만 갱신하며, 철회하면 동의 시각을 비운다.

    Args:
        data: ConsentRequestSchema로 검증한 {"terms", "privacy", "marketing"}.

    Raises:
        BusinessException: 유저가 없으면 USER_NOT_FOUND.
    """
    user = get_user(user_id)
    now = datetime.now(timezone.utc)

    if user.terms_agreed_at is None:
        user.terms_agreed_at = now
        user.privacy_agreed_at = now

    if data["marketing"] != user.marketing_agreed:
        user.marketing_agreed = data["marketing"]
        user.marketing_agreed_at = now if data["marketing"] else None

    db.session.commit()
    return user


def delete_user(user_id: int) -> int:
    """유저를 삭제하고 카카오 회원번호를 돌려준다. 리뷰는 FK의 ON DELETE CASCADE로 DB가 함께 삭제한다.

    commit하지 않는다. 호출자(auth.service.withdraw)가 토큰 폐기와 함께 한 번에 확정한다.

    Returns:
        삭제한 유저의 kakao_id. 호출자가 카카오 연결 끊기에 쓴다.

    Raises:
        BusinessException: 유저가 없으면 USER_NOT_FOUND.
    """
    user = get_user(user_id)
    # commit 이후에는 삭제된 객체의 속성을 읽을 수 없어 미리 꺼내 둔다.
    kakao_id = user.kakao_id
    db.session.delete(user)
    return kakao_id
