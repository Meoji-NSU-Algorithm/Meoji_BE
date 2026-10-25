"""모든 도메인 Blueprint를 /api 아래 하나로 묶는 부모 Blueprint.

새 도메인을 추가할 때는 해당 routes의 Blueprint를 import해 register_blueprint만 추가하면 된다.
자식 Blueprint의 url_prefix에는 "/api"를 다시 쓰지 않는다(/api/api/... 중복 방지).
"""
from flask import Blueprint

from app.domains.auth.routes import auth_bp
from app.domains.users.routes import users_bp
from app.domains.reviews.routes import review_bp
from app.domains.events.routes import events_bp

api_bp = Blueprint("api", __name__, url_prefix="/api")


api_bp.register_blueprint(auth_bp)
api_bp.register_blueprint(users_bp)
api_bp.register_blueprint(review_bp)
api_bp.register_blueprint(events_bp)
