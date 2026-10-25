"""모델 진입점. 모든 도메인 모델을 import해 Flask-Migrate(Alembic)가 테이블을 인식하게 한다."""
# 새 모델을 추가하면 여기에도 import해야 마이그레이션 autogenerate에 포함된다.
# app/__init__.py가 `from app import models`로 이 모듈을 불러온다.
from app.domains.users.models import User
from app.domains.auth.models import TokenBlocklist
from app.domains.reviews.models import Review

from app.domains.events.models import Category, Sido, Event, Tag, EventTag, EventDailyView
from app.domains.tour.models import TourSyncState

__all__ = ["User", "TokenBlocklist", "Review", "Category", "Sido", "Event", "Tag", "EventTag", "EventDailyView", "TourSyncState"]
