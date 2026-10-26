"""tour 단위 테스트 공통 fixture. 기준 데이터는 마이그레이션 시드와 동일하게 직접 넣는다."""
import pytest
from sqlalchemy.orm import Session

from app.core.extensions import db
from app.domains.events.models import Category, Sido, Tag
from app.domains.tour.models import TourSyncState

CATEGORIES = ["축제", "전시", "공연", "체험", "계절행사"]
# 마이그레이션 62d4e8a91b03의 SIDOS와 동일(29 광주, 46 전남은 없다).
SIDOS = ["11", "41", "26", "51", "44", "28", "27", "30", "31", "36", "43", "52", "12", "47", "48", "50"]
TAGS = ["불꽃놀이", "푸드트럭", "야간", "체험", "가족", "공연", "전시", "음악", "꽃", "먹거리"]


@pytest.fixture()
def seeded(app_ctx):
    for i, name in enumerate(CATEGORIES, 1):
        db.session.add(Category(name=name, sort_order=i))
    for i, code in enumerate(SIDOS, 1):
        db.session.add(Sido(code=code, name=f"시도{code}", short_name=code, sort_order=i))
    for name in TAGS:
        db.session.add(Tag(name=name))
    db.session.add(TourSyncState(id=1, last_success_at=None))
    db.session.commit()
    db.session.remove()
    return app_ctx


class FakeAPI:
    """TourAPI 대체. items는 목록 페이지(1페이지), common/intro는 contentid별 dict 또는 예외."""

    def __init__(self, items, common=None, intro=None, list_error=None):
        self.items = items
        self.common = common or {}
        self.intro = intro or {}
        self.list_error = list_error
        self.calls = []

    def iter_festivals(self, start_date=None, end_date=None):
        self.calls.append(("list", start_date, end_date))
        if self.list_error:
            raise self.list_error
        yield 1, list(self.items)

    def _get(self, table, cid):
        value = table.get(str(cid), {})
        if isinstance(value, Exception):
            raise value
        return dict(value)

    def festival_common(self, cid):
        return self._get(self.common, cid)

    def festival_intro(self, cid):
        return self._get(self.intro, cid)


def list_item(cid="1001", **kw):
    base = {
        "contentid": cid, "contenttypeid": "15", "title": f"축제{cid}",
        "eventstartdate": "20261001", "eventenddate": "20261005",
        "lDongRegnCd": "44", "lclsSystm3": "EV010100",
        "mapx": "127.15", "mapy": "36.80", "modifiedtime": "20261001120000",
    }
    base.update(kw)
    return base
