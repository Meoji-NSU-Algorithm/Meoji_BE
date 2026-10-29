"""약관 동의 스키마와 users.service.save_consent 단위 테스트."""
import pytest
from marshmallow import ValidationError

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.users import service
from app.domains.users.models import User
from app.domains.users.schemas import ConsentRequestSchema, ConsentResponseSchema


def _make_user():
    user = User(kakao_id=1, email="a@b.com", nickname="n")
    db.session.add(user)
    db.session.commit()
    return user


def test_request_schema_defaults_marketing_false():
    """marketing을 생략하면 false로 채워진다."""
    assert ConsentRequestSchema().load({"terms": True, "privacy": True}) == {
        "terms": True, "privacy": True, "marketing": False}


def test_request_schema_terms_false_message():
    """terms가 false면 한국어 메시지로 거절된다."""
    with pytest.raises(ValidationError) as e:
        ConsentRequestSchema().load({"terms": False, "privacy": True})
    assert e.value.messages == {"terms": ["서비스 이용약관에 동의해야 합니다."]}


def test_request_schema_privacy_false_message():
    """privacy가 false면 한국어 메시지로 거절된다."""
    with pytest.raises(ValidationError) as e:
        ConsentRequestSchema().load({"terms": True, "privacy": False})
    assert e.value.messages == {"privacy": ["개인정보 처리방침에 동의해야 합니다."]}


def test_request_schema_missing_required():
    """terms/privacy가 없으면 필수 필드 오류다."""
    with pytest.raises(ValidationError) as e:
        ConsentRequestSchema().load({})
    assert set(e.value.messages) == {"terms", "privacy"}


def test_request_schema_rejects_unknown_field():
    """정의되지 않은 필드는 거절된다."""
    with pytest.raises(ValidationError) as e:
        ConsentRequestSchema().load({"terms": True, "privacy": True, "extra": 1})
    assert "extra" in e.value.messages


def test_response_schema_nulls_before_consent():
    """동의 전 유저는 시각이 null로 직렬화된다."""
    u = User(kakao_id=1, email="a@b.com", nickname="n", marketing_agreed=False)
    assert ConsentResponseSchema().dump(u) == {
        "terms_agreed_at": None, "privacy_agreed_at": None,
        "marketing_agreed": False, "marketing_agreed_at": None}


def test_save_consent_sets_both_required_times_equal(app_ctx):
    """처음 동의하면 이용약관/개인정보 동의 시각이 같은 값으로 채워진다."""
    user = _make_user()
    service.save_consent(user.id, {"terms": True, "privacy": True, "marketing": False})
    assert user.terms_agreed_at is not None
    assert user.terms_agreed_at == user.privacy_agreed_at
    assert user.marketing_agreed is False and user.marketing_agreed_at is None


def test_save_consent_keeps_terms_time_and_toggles_marketing(app_ctx):
    """재호출 시 약관 시각은 유지되고 marketing은 켜면 시각이 생기고 끄면 비워진다."""
    user = _make_user()
    service.save_consent(user.id, {"terms": True, "privacy": True, "marketing": False})
    first = user.terms_agreed_at

    service.save_consent(user.id, {"terms": True, "privacy": True, "marketing": True})
    assert user.terms_agreed_at == first
    assert user.marketing_agreed is True and user.marketing_agreed_at is not None

    service.save_consent(user.id, {"terms": True, "privacy": True, "marketing": False})
    assert user.marketing_agreed is False and user.marketing_agreed_at is None


def test_save_consent_unknown_user(app_ctx):
    """없는 유저면 USER_NOT_FOUND."""
    with pytest.raises(BusinessException) as e:
        service.save_consent(999, {"terms": True, "privacy": True, "marketing": False})
    assert e.value.error_code == ErrorCode.USER_NOT_FOUND


def test_delete_user_unknown_user(app_ctx):
    """없는 유저의 삭제는 USER_NOT_FOUND."""
    with pytest.raises(BusinessException) as e:
        service.delete_user(999)
    assert e.value.error_code == ErrorCode.USER_NOT_FOUND
