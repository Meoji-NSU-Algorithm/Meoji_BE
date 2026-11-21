"""users.service 단위 테스트 (실제 테스트 DB 사용)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.users import service
from app.domains.users.models import User


def _info(**over):
    info = {"kakao_id": 1001, "email": "a@b.com", "nickname": "nick", "profile_image": "http://img"}
    info.update(over)
    return info


def _count():
    return db.session.scalar(db.select(db.func.count()).select_from(User))


def test_creates_new_user(app_ctx):
    """처음 온 사용자는 생성되고 created=True, id가 채워진다."""
    user, created = service.get_or_create_kakao_user(_info())
    assert created is True
    assert user.id is not None
    assert (user.kakao_id, user.email, user.nickname, user.profile_image) == (1001, "a@b.com", "nick", "http://img")
    assert _count() == 1


def test_returns_existing_user(app_ctx):
    """기존 kakao_id 사용자는 created=False로 같은 유저를 반환한다."""
    first, _ = service.get_or_create_kakao_user(_info())
    second, created = service.get_or_create_kakao_user(_info())
    assert created is False
    assert second.id == first.id
    assert _count() == 1


def test_updates_nickname_and_profile_but_not_email(app_ctx):
    """닉네임/프로필은 갱신되고 이메일은 가입 시점 값이 유지된다."""
    service.get_or_create_kakao_user(_info())
    user, created = service.get_or_create_kakao_user(_info(nickname="new", profile_image=None, email="changed@b.com"))
    assert created is False
    db.session.expire_all()
    stored = db.session.scalar(db.select(User).filter_by(kakao_id=1001))
    assert stored.nickname == "new"
    assert stored.profile_image is None
    assert stored.email == "a@b.com"


def test_email_conflict_with_other_kakao_id(app_ctx):
    """같은 이메일을 다른 kakao_id가 쓰면 USER_EMAIL_CONFLICT이고 세션이 정상 복구된다."""
    service.get_or_create_kakao_user(_info())
    with pytest.raises(BusinessException) as e:
        service.get_or_create_kakao_user(_info(kakao_id=2002))
    assert e.value.error_code == ErrorCode.USER_EMAIL_CONFLICT
    assert _count() == 1
    # 롤백 후 세션이 계속 사용 가능해야 한다.
    user, created = service.get_or_create_kakao_user(_info(kakao_id=3003, email="other@b.com"))
    assert created is True


def test_integrity_race_returns_existing(app_ctx, monkeypatch):
    """동시 가입으로 commit이 IntegrityError면 재조회한 기존 유저를 (user, False)로 반환한다."""
    real_commit = db.session.commit
    state = {"n": 0}

    def racing_commit():
        state["n"] += 1
        if state["n"] == 1:
            # 별도 커넥션에서 경쟁 가입을 먼저 확정시킨다.
            with db.engine.begin() as conn:
                conn.execute(text(
                    "INSERT INTO user (kakao_id, email, nickname, created_at, updated_at) "
                    "VALUES (1001, 'a@b.com', 'rival', NOW(), NOW())"
                ))
        return real_commit()

    monkeypatch.setattr(db.session, "commit", racing_commit)
    user, created = service.get_or_create_kakao_user(_info())
    assert created is False
    assert user.kakao_id == 1001
    assert user.nickname == "rival"
    assert _count() == 1


def test_integrity_error_unknown_cause_conflict(app_ctx, monkeypatch):
    """kakao_id로도 못 찾는 IntegrityError는 USER_EMAIL_CONFLICT로 처리된다."""
    def boom():
        raise IntegrityError("stmt", {}, Exception("dup"))
    monkeypatch.setattr(db.session, "commit", boom)
    with pytest.raises(BusinessException) as e:
        service.get_or_create_kakao_user(_info())
    assert e.value.error_code == ErrorCode.USER_EMAIL_CONFLICT


def test_get_user_found(app_ctx):
    """존재하는 id는 User를 반환한다."""
    user, _ = service.get_or_create_kakao_user(_info())
    assert service.get_user(user.id).id == user.id


@pytest.mark.parametrize("uid", [0, 99999, -1])
def test_get_user_not_found(app_ctx, uid):
    """없는 id는 USER_NOT_FOUND이다."""
    with pytest.raises(BusinessException) as e:
        service.get_user(uid)
    assert e.value.error_code == ErrorCode.USER_NOT_FOUND


def test_missing_info_key_raises_keyerror(app_ctx):
    """필수 키가 빠진 info는 KeyError가 난다(kakao_client가 보장하는 계약)."""
    with pytest.raises(KeyError):
        service.get_or_create_kakao_user({"kakao_id": 1})
