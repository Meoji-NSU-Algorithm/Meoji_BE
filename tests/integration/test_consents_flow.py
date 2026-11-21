"""약관 동의 API(POST/GET /api/users/me/consents) HTTP 통합 테스트."""
from tests.integration.test_auth_flow import assert_error

URL = "/api/users/me/consents"
OK = {"terms": True, "privacy": True}


def test_terms_false_returns_400(client, login):
    """이용약관에 동의하지 않으면 400 COMMON_INVALID_INPUT."""
    h, _, _ = login()
    assert_error(client.post(URL, headers=h, json={"terms": False, "privacy": True}), 400, "COMMON_INVALID_INPUT")


def test_privacy_false_returns_400(client, login):
    """개인정보 처리방침에 동의하지 않으면 400."""
    h, _, _ = login()
    assert_error(client.post(URL, headers=h, json={"terms": True, "privacy": False}), 400, "COMMON_INVALID_INPUT")


def test_privacy_missing_returns_400(client, login):
    """privacy를 빠뜨리면 400."""
    h, _, _ = login()
    assert_error(client.post(URL, headers=h, json={"terms": True}), 400, "COMMON_INVALID_INPUT")


def test_empty_body_returns_400(client, login):
    """본문이 없어도 400이다."""
    h, _, _ = login()
    assert_error(client.post(URL, headers=h), 400, "COMMON_INVALID_INPUT")


def test_rejected_consent_is_not_saved(client, login):
    """거절된 요청은 아무것도 저장하지 않는다."""
    h, _, _ = login()
    client.post(URL, headers=h, json={"terms": False, "privacy": True, "marketing": True})
    data = client.get(URL, headers=h).get_json()["data"]
    assert data["terms_agreed_at"] is None and data["marketing_agreed"] is False


def test_success_defaults_marketing_false(client, login):
    """성공하면 약관 시각이 채워지고 marketing은 기본 false, 시각은 null이다."""
    h, _, _ = login()
    resp = client.post(URL, headers=h, json=OK)
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["terms_agreed_at"] and data["terms_agreed_at"].endswith("+00:00")
    assert data["privacy_agreed_at"]
    assert data["marketing_agreed"] is False
    assert data["marketing_agreed_at"] is None


def test_second_post_keeps_first_terms_time(client, login):
    """다시 동의해도 최초 약관 동의 시각은 바뀌지 않는다."""
    h, _, _ = login()
    first = client.post(URL, headers=h, json=OK).get_json()["data"]
    second = client.post(URL, headers=h, json={**OK, "marketing": True}).get_json()["data"]
    assert second["terms_agreed_at"] == first["terms_agreed_at"]
    assert second["privacy_agreed_at"] == first["privacy_agreed_at"]


def test_marketing_true_then_false_sets_and_clears_time(client, login):
    """marketing 동의 시 시각이 생기고 철회하면 비워진다."""
    h, _, _ = login()
    on = client.post(URL, headers=h, json={**OK, "marketing": True}).get_json()["data"]
    assert on["marketing_agreed"] is True and on["marketing_agreed_at"]

    off = client.post(URL, headers=h, json={**OK, "marketing": False}).get_json()["data"]
    assert off["marketing_agreed"] is False and off["marketing_agreed_at"] is None
    assert client.get(URL, headers=h).get_json()["data"] == off


def test_marketing_unchanged_keeps_time(client, login):
    """marketing 값이 같으면 동의 시각을 갱신하지 않는다."""
    h, _, _ = login()
    first = client.post(URL, headers=h, json={**OK, "marketing": True}).get_json()["data"]
    second = client.post(URL, headers=h, json={**OK, "marketing": True}).get_json()["data"]
    assert second["marketing_agreed_at"] == first["marketing_agreed_at"]


def test_get_before_consent_returns_nulls(client, login):
    """동의 전 조회는 시각이 null이고 marketing_agreed는 false다."""
    h, _, _ = login()
    resp = client.get(URL, headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {
        "terms_agreed_at": None, "privacy_agreed_at": None,
        "marketing_agreed": False, "marketing_agreed_at": None,
    }


def test_consents_are_per_user(client, login):
    """다른 유저의 동의는 내 조회에 영향을 주지 않는다."""
    h1, _, _ = login(kakao_id=1)
    h2, _, _ = login(kakao_id=2)
    client.post(URL, headers=h1, json={**OK, "marketing": True})
    assert client.get(URL, headers=h2).get_json()["data"]["terms_agreed_at"] is None


def test_consents_require_token(client):
    """토큰이 없으면 POST/GET 모두 401."""
    assert_error(client.post(URL, json=OK), 401, "AUTH_UNAUTHORIZED")
    assert_error(client.get(URL), 401, "AUTH_UNAUTHORIZED")
