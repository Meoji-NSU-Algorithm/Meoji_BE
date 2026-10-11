
# directions 패키지의 진입점.
# 실제 라우트는 routes.py에 있지만, 여기서 directions_bp를 다시 내보낸다.
# 다른 파일에서는 routes.py의 위치를 몰라도
#     from app.api.directions import directions_bp
# 처럼 가져올 수 있다.
from app.api.directions.routes import directions_bp

# 외부에 공개할 이름을 명시적으로 제한한다.
__all__ = ["directions_bp"]
