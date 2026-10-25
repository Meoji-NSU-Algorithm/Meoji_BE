# models 패키지의 진입점(entrypoint).
# 각 모델 모듈(user.py, token_blocklist.py 등)에 흩어진 모델 클래스를
# 여기 한 곳에 모아 import해두면, 다른 코드에서는
#   from app.models import User, TokenBlocklist
# 처럼 짧게 가져다 쓸 수 있다.
#
# 또한 Flask-Migrate(Alembic)가 마이그레이션 파일을 자동 생성(autogenerate)하려면
# db.Model을 상속한 모델 클래스들이 파이썬 프로세스에 "import되어" 있어야 하는데,
# app/__init__.py에서 `from app import models`로 이 파일을 import하는 것만으로

# 아래 모델들이 함께 로드되게 만드는 역할도 한다.
from app.domains.users.models import User                      # User 모델을 이 패키지 네임스페이스로 노출
from app.domains.auth.models import TokenBlocklist  # TokenBlocklist 모델을 이 패키지 네임스페이스로 노출
from app.domains.reviews.models import Review                   # Review 모델을 이 패키지 네임스페이스로 노출

# 이 모듈에 모델 클래스를 import해야 Flask-Migrate가 테이블을 인식한다.
# User/TokenBlocklist는 기존 인증 도메인이고, 행사 모델 여섯 개와
# 예약 상태 모델 하나는 축제 조회·갱신 도메인에서 사용한다.
from app.domains.events.models import Category, Sido, Event, Tag, EventTag, EventDailyView
# 예약 상태도 모델 메타데이터에 등록해야 Alembic이 테이블을 인식한다.
from app.domains.tour.models import TourSyncState

# `__all__`은 `from app.models import *`를 사용할 때 외부로 내보낼 이름 목록이다.
# 모델 등록 자체에는 위 import만 필요하므로 필수는 아니지만, 공개할 모델을
# 명시하고 내부의 db/헬퍼 이름이 실수로 노출되지 않도록 유지한다.
__all__ = ["User", "TokenBlocklist", "Review", "Category", "Sido", "Event", "Tag", "EventTag", "EventDailyView", "TourSyncState"]
