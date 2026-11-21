"""kopis 단위 테스트 공통 fixture. 시도는 KOPIS area와 이름으로 맞추므로 실제 이름으로 넣는다."""
from pathlib import Path

import pytest

from app.core.extensions import db
from app.domains.events.models import Category, Sido
from app.domains.tour.models import TourSyncState

FIXTURES = Path(__file__).parent / "fixtures"
CATEGORIES = ["축제", "전시", "공연", "체험", "계절행사"]
SIDOS = [("11", "서울특별시"), ("27", "대구광역시"), ("12", "전남광주통합특별시")]


@pytest.fixture()
def seeded(app_ctx):
    for i, name in enumerate(CATEGORIES, 1):
        db.session.add(Category(name=name, sort_order=i))
    for i, (code, name) in enumerate(SIDOS, 1):
        db.session.add(Sido(code=code, name=name, short_name=name[:2], sort_order=i))
    db.session.add(TourSyncState(id=1, last_success_at=None))
    db.session.commit()
    db.session.remove()
    return app_ctx


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()
