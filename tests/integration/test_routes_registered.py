"""등록된 URL 목록을 고정해 실수로 경로가 바뀌면 실패하게 한다."""

EXPECTED_ROUTES = {
    ("POST", "/api/auth/kakao"): "api.auth.kakao_login",
    ("POST", "/api/auth/refresh"): "api.auth.refresh_token",
    ("POST", "/api/auth/logout"): "api.auth.logout",
    ("GET", "/api/users/me"): "api.users.get_user",
    ("DELETE", "/api/users/me"): "api.users.withdraw_user",
    ("GET", "/api/users/me/consents"): "api.users.get_consents",
    ("POST", "/api/users/me/consents"): "api.users.save_consents",
    ("POST", "/api/reviews"): "api.reviews.create_review",
    ("GET", "/api/reviews/event/<int:event_id>"): "api.reviews.list_event_reviews",
    ("GET", "/api/reviews/event/<int:event_id>/rating"): "api.reviews.get_event_rating",
    ("GET", "/api/reviews/my"): "api.reviews.list_my_reviews",
    ("PUT", "/api/reviews/<int:review_id>"): "api.reviews.update_review",
    ("DELETE", "/api/reviews/<int:review_id>"): "api.reviews.delete_review",
    ("POST", "/api/reviews/images"): "api.reviews.upload_image",
    ("GET", "/api/events/categories"): "api.events.list_categories",
    ("GET", "/api/events/sidos"): "api.events.list_sidos",
    ("GET", "/api/events"): "api.events.list_events",
    ("GET", "/api/events/monthly-top"): "api.events.monthly_top_events",
    ("GET", "/api/events/<int:event_id>"): "api.events.get_event",
}


def _api_routes(app):
    routes = {}
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api"):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            routes[(method, rule.rule)] = rule.endpoint
    return routes


def test_exact_set_of_api_routes(app):
    """/api 아래 (메서드, 경로)와 endpoint 이름이 기대 목록과 정확히 같다."""
    assert _api_routes(app) == EXPECTED_ROUTES


def test_no_duplicated_api_prefix(app):
    """/api/api 중복 prefix가 없다."""
    assert not [r for r in app.url_map.iter_rules() if r.rule.startswith("/api/api")]


def test_only_api_and_static_routes_exist(app):
    """/api 외 경로는 static뿐이다."""
    others = {r.rule for r in app.url_map.iter_rules() if not r.rule.startswith("/api")}
    assert others <= {"/static/<path:filename>"}
