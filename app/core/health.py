"""서버와 DB가 요청을 처리할 수 있는지 확인하는 헬스체크 API."""
from flask import Blueprint, jsonify
from sqlalchemy import text

from app.core.extensions import db
from app.core.response import CommonResponse

# 부모 Blueprint(api_bp)가 /api를 붙인다. 인증 없이 호출할 수 있다.
health_bp = Blueprint("health", __name__)


@health_bp.get("/health")
def health_check():
    """SELECT 1로 DB 연결을 확인한다. 접속 실패는 공통 DB 오류 핸들러가 503으로 응답한다."""
    db.session.execute(text("SELECT 1"))
    return jsonify(CommonResponse.success({"status": "ok"})), 200
