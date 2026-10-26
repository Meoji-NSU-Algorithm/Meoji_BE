"""인증 전체 흐름(로그인, 내 정보, 재발급, 로그아웃) HTTP 통합 테스트."""

ERROR_KEYS = {"success", "code", "message"}


def assert_error(resp, status, code):
    """에러 응답이 공통 형식이고 기대한 상태/코드인지 확인한다."""
    body = resp.get_json()
    assert resp.status_code == status, body
    assert body["success"] is False
    assert body["code"] == code
    assert ERROR_KEYS <= set(body)
    return body


def test_full_user_journey(client, login, bearer):
    """로그인부터 재발급, 로그아웃까지 한 사용자의 전체 흐름이 이어진다."""
    headers, tokens, user_id = login(kakao_id=7, email="a@test.com", nickname="에이")
    assert set(tokens) == {"access_token", "refresh_token", "is_new_user"}
    assert tokens["is_new_user"] is True

    me = client.get("/api/users/me", headers=headers).get_json()
    assert me["success"] is True
    assert me["data"] == {"id": user_id, "email": "a@test.com", "nickname": "에이", "profile_image": None}

    # 재로그인하면 같은 유저이고 신규가 아니다.
    headers2, tokens2, user_id2 = login(kakao_id=7, email="a@test.com", nickname="에이")
    assert user_id2 == user_id
    assert tokens2["is_new_user"] is False

    # refresh rotation
    resp = client.post("/api/auth/refresh", headers=bearer(tokens2["refresh_token"]))
    assert resp.status_code == 200
    new = resp.get_json()["data"]
    assert set(new) == {"access_token", "refresh_token"}
    assert new["refresh_token"] != tokens2["refresh_token"]

    # 사용한 refresh 재사용 -> 폐기됨
    assert_error(client.post("/api/auth/refresh", headers=bearer(tokens2["refresh_token"])),
                 401, "AUTH_TOKEN_REVOKED")

    # 새 토큰으로 로그아웃
    new_headers = bearer(new["access_token"])
    assert client.get("/api/users/me", headers=new_headers).status_code == 200
    resp = client.post("/api/auth/logout", headers=new_headers, json={"refresh_token": new["refresh_token"]})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert_error(client.get("/api/users/me", headers=new_headers), 401, "AUTH_TOKEN_REVOKED")
    assert_error(client.post("/api/auth/refresh", headers=bearer(new["refresh_token"])),
                 401, "AUTH_TOKEN_REVOKED")


def test_logout_twice_is_rejected_with_revoked_access(client, login):
    """로그아웃된 access 토큰으로 다시 로그아웃하면 401 AUTH_TOKEN_REVOKED."""
    headers, tokens, _ = login()
    body = {"refresh_token": tokens["refresh_token"]}
    assert client.post("/api/auth/logout", headers=headers, json=body).status_code == 200
    assert_error(client.post("/api/auth/logout", headers=headers, json=body), 401, "AUTH_TOKEN_REVOKED")


def test_logout_again_with_fresh_access_is_idempotent(client, login, bearer):
    """이미 폐기된 refresh를 body에 넣어도 새 access로 로그아웃하면 200이다."""
    headers, tokens, _ = login(kakao_id=1)
    client.post("/api/auth/logout", headers=headers, json={"refresh_token": tokens["refresh_token"]})
    headers2, _, _ = login(kakao_id=1)
    resp = client.post("/api/auth/logout", headers=headers2, json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200


def test_logout_with_other_users_refresh_is_invalid(client, login):
    """남의 refresh 토큰으로는 로그아웃할 수 없다."""
    headers, _, _ = login(kakao_id=1)
    _, other_tokens, _ = login(kakao_id=2)
    resp = client.post("/api/auth/logout", headers=headers, json={"refresh_token": other_tokens["refresh_token"]})
    assert_error(resp, 401, "AUTH_TOKEN_INVALID")


def test_logout_with_garbage_refresh_is_invalid(client, login):
    """위조된 refresh 토큰 문자열은 AUTH_TOKEN_INVALID(500 아님)."""
    headers, _, _ = login()
    resp = client.post("/api/auth/logout", headers=headers, json={"refresh_token": "not-a-jwt"})
    assert_error(resp, 401, "AUTH_TOKEN_INVALID")


def test_logout_bad_body_returns_400(client, login):
    """logout body에 refresh_token이 없거나 비면 400 COMMON_INVALID_INPUT."""
    headers, _, _ = login()
    for payload in ({}, {"refresh_token": ""}):
        body = assert_error(client.post("/api/auth/logout", headers=headers, json=payload),
                            400, "COMMON_INVALID_INPUT")
        assert "refresh_token" in body["errors"]
    resp = client.post("/api/auth/logout", headers=headers, data="not json",
                       content_type="text/plain")
    assert_error(resp, 400, "COMMON_INVALID_INPUT")


def test_kakao_login_bad_body_returns_400(client, kakao_profiles):
    """code가 없거나 비어 있으면 400 COMMON_INVALID_INPUT."""
    for payload in ({}, {"code": ""}, {"code": 123}):
        body = assert_error(client.post("/api/auth/kakao", json=payload), 400, "COMMON_INVALID_INPUT")
        assert "code" in body["errors"]
    assert_error(client.post("/api/auth/kakao"), 400, "COMMON_INVALID_INPUT")


def test_missing_authorization_header_returns_401(client):
    """Authorization 헤더가 없으면 401 AUTH_UNAUTHORIZED 공통 형식."""
    assert_error(client.get("/api/users/me"), 401, "AUTH_UNAUTHORIZED")
    assert_error(client.post("/api/auth/refresh"), 401, "AUTH_UNAUTHORIZED")
    assert_error(client.post("/api/auth/logout", json={"refresh_token": "x"}), 401, "AUTH_UNAUTHORIZED")


def test_refresh_with_access_token_is_rejected(client, login, bearer):
    """refresh 엔드포인트에 access 토큰을 보내면 500이 아니라 401 AUTH_TOKEN_INVALID."""
    _, tokens, _ = login()
    resp = client.post("/api/auth/refresh", headers=bearer(tokens["access_token"]))
    assert_error(resp, 401, "AUTH_TOKEN_INVALID")


def test_access_endpoint_with_refresh_token_is_rejected(client, login, bearer):
    """access 전용 엔드포인트에 refresh 토큰을 보내면 401 AUTH_TOKEN_INVALID."""
    _, tokens, _ = login()
    assert_error(client.get("/api/users/me", headers=bearer(tokens["refresh_token"])),
                 401, "AUTH_TOKEN_INVALID")


def test_garbage_bearer_token_is_invalid(client, bearer):
    """형식이 깨진 토큰은 401 AUTH_TOKEN_INVALID."""
    assert_error(client.get("/api/users/me", headers=bearer("abc.def.ghi")), 401, "AUTH_TOKEN_INVALID")


def test_refresh_for_deleted_user_is_401_invalid(client, login, bearer, app_ctx):
    """토큰의 유저가 사라졌으면 404가 아니라 401 AUTH_TOKEN_INVALID이고 재시도도 막힌다."""
    from app.core.extensions import db
    from app.domains.users.models import User
    _, tokens, _ = login()
    db.session.execute(db.delete(User))
    db.session.commit()
    resp = client.post("/api/auth/refresh", headers=bearer(tokens["refresh_token"]))
    assert_error(resp, 401, "AUTH_TOKEN_INVALID")
    assert_error(client.post("/api/auth/refresh", headers=bearer(tokens["refresh_token"])), 401, "AUTH_TOKEN_REVOKED")
