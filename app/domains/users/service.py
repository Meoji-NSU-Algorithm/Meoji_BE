"""유저 조회/생성/삭제, 약관 동의, 프로필 사진을 담당하는 서비스. JWT와 카카오 통신은 모르고 user 테이블만 다룬다."""
import uuid

from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.images import convert_to_webp, read_upload
from app.core.storage import delete_objects, put_object
from app.core.time import utcnow
from app.domains.users.models import User

# 프로필 사진 제한. 리뷰 제한(reviews/images.py)과 따로 정한다.
PROFILE_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PROFILE_MAX_SIDE = 512


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
            kakao_profile_image=info["profile_image"],
        )
        db.session.add(user)
    else:
        # 닉네임과 카카오 사진은 로그인 때마다 최신 값으로 갱신한다. 이메일은 가입 시점의 값을 유지한다.
        # 화면에 보여줄 사진(profile_image_source)은 바꾸지 않아, 사용자가 고른 사진이 유지된다.
        user.nickname = info["nickname"]
        user.kakao_profile_image = info["profile_image"]

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
    now = utcnow()

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


def set_custom_profile_image(user_id: int, files: list) -> User:
    """올린 사진 한 장을 webp로 바꿔 저장하고, 직접 올린 사진을 보여주도록 바꾼다.

    Args:
        files: image 필드로 올라온 파일(werkzeug FileStorage) 목록. 정확히 한 장이어야 한다.

    Raises:
        BusinessException: 유저가 없으면 USER_NOT_FOUND, 사진이 없거나 2장 이상이면 COMMON_INVALID_INPUT,
            용량 초과면 IMAGE_TOO_LARGE, 이미지가 아니면 IMAGE_INVALID, 저장소 문제면 IMAGE_STORAGE_UNAVAILABLE.
    """
    user = get_user(user_id)
    if len(files) != 1:
        raise BusinessException(ErrorCode.COMMON_INVALID_INPUT, extra={"errors": {"image": ["사진을 한 장 올려주세요."]}})

    raw = read_upload(files[0], max_bytes=PROFILE_MAX_UPLOAD_BYTES)
    data = convert_to_webp(raw, max_side=PROFILE_MAX_SIDE)

    # key는 서버가 랜덤으로 만든다. 사용자가 보낸 파일 이름은 쓰지 않는다.
    key = f"profiles/{uuid.uuid4().hex}.webp"
    put_object(key, data, "image/webp")

    old_key = user.custom_profile_image_key
    user.custom_profile_image_key = key
    user.profile_image_source = "custom"
    _commit_or_delete(key)

    # 커밋 뒤 정리라 실패해도 요청을 실패시키지 않는다(delete_objects가 로그만 남긴다).
    delete_objects([old_key] if old_key else [])
    return user


def set_profile_image_source(user_id: int, source: str) -> User:
    """카카오 사진(kakao) 또는 기본 이미지(default)로 바꾸고, 직접 올린 사진 파일은 지운다.

    Raises:
        BusinessException: 유저가 없으면 USER_NOT_FOUND.
    """
    user = get_user(user_id)
    old_key = user.custom_profile_image_key
    user.profile_image_source = source
    user.custom_profile_image_key = None
    db.session.commit()

    delete_objects([old_key] if old_key else [])
    return user


def _commit_or_delete(new_key: str) -> None:
    """커밋한다. 실패하면 이번 요청에서 올린 사진을 지워 어디에도 붙지 않은 파일이 남지 않게 한다."""
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        delete_objects([new_key])
        raise


def profile_image_keys_to_delete_on_withdraw(user_id: int) -> set[str]:
    """탈퇴로 지울 프로필 사진 key. 유저가 지워지기 전에 호출한다."""
    key = get_user(user_id).custom_profile_image_key

    return {key} if key else set()
