"""KOPIS 공연을 events에 저장하는 수집 서비스.

TourAPI 수집과 같은 events 테이블을 쓰고, 출처를 구분하려고 tour_content_id에
'KOPIS-<공연ID>'를 넣는다. 같은 공연이 TourAPI에 있으면 TourAPI를 우선해 저장하지 않는다.
상세·시설 API는 처음 보는 공연에만 부르고, 이미 저장된 공연은 목록 값으로만 갱신한다.
건마다 별도 트랜잭션이라 실패한 건만 롤백된다. 목록에서 사라진 공연은 지우지 않는다.
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from sqlalchemy import delete, exists, select, update
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.time import KST
from app.domains.bookmarks.models import Bookmark
from app.domains.events.models import Category, Event, Sido
from app.domains.kopis.client import KopisAPI
from app.domains.reviews.models import Review
from app.domains.tour.sync_service import _fee, _homepage_url

ID_PREFIX = "KOPIS-"
# KOPIS 장르(genrenm) -> 우리 카테고리 이름. 여기 없는 장르는 수집하지 않는다.
GENRE_CATEGORY = {
    "연극": "공연",
    "뮤지컬": "공연",
    "서양음악(클래식)": "공연",
    "한국음악(국악)": "공연",
    "대중음악": "공연",
    "무용(서양/한국무용)": "공연",
    "대중무용": "공연",
    "서커스/마술": "공연",
    "복합": "공연",
}
LOOKAHEAD_DAYS = 30
# 이미 저장된 공연도 이 주기(일)마다 상세를 다시 받아 가격·시간·좌표 변경을 반영한다.
# 행마다 id % 주기로 요일을 나눠 하루 호출이 한꺼번에 몰리지 않게 한다.
DETAIL_REFRESH_DAYS = 7
# TourAPI 행사와 제목 유사도가 이 값 이상이면 같은 행사로 본다. 공연장이 같으면 기준을 낮추고,
# 양쪽 공연장이 모두 있는데 다르면 중복으로 보지 않는다.
SIMILAR_TITLE = 0.85
SIMILAR_TITLE_SAME_VENUE = 0.6
# 비교 전에 지우는 표기. '[대학로]' 같은 지역 꼬리표, 연도·회차, 공백·기호.
_TITLE_NOISE = re.compile(r"\[[^\]]*\]|(19|20)\d{2}년?|제\s*\d+\s*회|\d+\s*회|[^0-9a-z가-힣]")
_VENUE_PARENS = re.compile(r"\([^)]*\)?")
_WORD = "0-9a-z가-힣"


def _text(value, column):
    """빈 값은 None, 컬럼 길이를 넘으면 잘라서 반환한다."""
    if not value:
        return None
    limit = getattr(Event.__table__.columns[column].type, "length", None)
    return value[:limit] if limit else value


def _date(value, field):
    """'2026.11.28'을 date로. 형식이 틀리면 TOUR_SYNC_INVALID_DATA."""
    try:
        return datetime.strptime(value or "", "%Y.%m.%d").date()
    except ValueError as error:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"field": field, "reason": "invalid_date", "value": value}
        ) from error


def _modified(value):
    """updatedate('2026-11-06 15:00:03.112494')를 초 단위 datetime으로. 형식이 다르면 None."""
    try:
        return datetime.strptime((value or "")[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _coordinate(value, bound):
    """좌표 문자열을 DECIMAL(10,7)에 맞춰 반올림한다. 비었거나 범위 밖이면 None."""
    try:
        number = Decimal(value).quantize(Decimal("0.0000001"))
    except (InvalidOperation, TypeError):
        return None
    return number if number.is_finite() and abs(number) <= bound else None


def normalize_title(title):
    """비교용 제목. 소문자로 바꾸고 지역 꼬리표·연도·회차·공백·기호를 뺀다."""
    return _TITLE_NOISE.sub("", (title or "").lower())


def similar_titles(a, b, threshold=SIMILAR_TITLE, min_contain=4):
    """정규화한 제목이 같거나, 한쪽이 다른 쪽을 포함하거나(짧은 쪽이 min_contain자 이상), 유사도가 threshold 이상이면 True."""
    x, y = normalize_title(a), normalize_title(b)
    if not x or not y:
        return False
    if x == y or (min(len(x), len(y)) >= min_contain and (x in y or y in x)):
        return True
    return SequenceMatcher(None, x, y).ratio() >= threshold


def _venue_words(value):
    """괄호 부분을 빼고 소문자로 바꾼 뒤 낱말 사이를 공백 하나로 맞춘다."""
    text = _VENUE_PARENS.sub(" ", (value or "").lower())
    return " ".join(re.findall(f"[{_WORD}]+", text))


def _same_venue(a, b):
    """짧은 쪽 공연장 이름이 긴 쪽 안에 낱말 단위로 들어 있으면 같은 곳으로 본다.

    '벡스코 (BEXCO)'와 '부산 벡스코 제1전시장'은 같고, '피크닉'과 '서래섬 피크닉장'은 다르다.
    """
    x, y = sorted((_venue_words(a), _venue_words(b)), key=len)
    if len(x.replace(" ", "")) < 2:
        return False
    # 짧은 쪽의 글자 사이 공백은 있어도 없어도 되게 하고('대학로 극장' == '대학로극장'), 앞뒤는 낱말 경계여야 한다.
    chars = [re.escape(ch) for ch in x.replace(" ", "")]
    return re.search(f"(?<![{_WORD}])" + r"\s?".join(chars) + f"(?![{_WORD}])", y) is not None


def find_tour_duplicate(session, title, venue, sido_code, start, end):
    """같은 시도·겹치는 기간의 KOPIS 외(TourAPI) 행사 중 제목이 비슷한 것을 찾는다. 없으면 None."""
    candidates = session.scalars(
        select(Event).where(
            ~Event.tour_content_id.startswith(ID_PREFIX),
            Event.sido_code == sido_code,
            Event.start_date <= end,
            Event.end_date >= start,
        )
    )
    for event in candidates:
        if venue and event.venue_name:
            # 같은 작품이 공연장마다 따로 열리는 경우(전용관 여러 곳)가 있어, 공연장이 다르면 별개로 본다.
            if not _same_venue(venue, event.venue_name):
                continue
            # 같은 공연장이면 '진연'처럼 짧은 제목도 포함 관계로 인정한다('국악공연 진연').
            threshold, min_contain = SIMILAR_TITLE_SAME_VENUE, 2
        else:
            threshold, min_contain = SIMILAR_TITLE, 4
        if similar_titles(title, event.title, threshold, min_contain):
            return event
    return None


class KopisSyncService:
    """KOPIS 공연을 Event로 저장한다. api와 engine은 테스트 주입용이다."""

    def __init__(self, api=None, engine=None):
        self._api = api
        self.engine = engine if engine is not None else db.engine
        self._facilities = {}  # 한 번의 수집 동안 시설 상세를 재사용한다.

    @property
    def api(self):
        if self._api is None:
            self._api = KopisAPI()
        return self._api

    def _facility(self, facility_id):
        if not facility_id:
            return {}
        if facility_id not in self._facilities:
            self._facilities[facility_id] = self.api.facility(facility_id)
        return self._facilities[facility_id]

    @staticmethod
    def _move_bookmarks(session, from_id, to_id):
        """지울 행사의 찜을 남길 행사로 옮긴다. 둘 다 찜한 사용자는 지울 쪽 찜만 지운다(UNIQUE 제약)."""
        # MySQL은 같은 테이블을 서브쿼리로 읽으며 지울 수 없어(1093) 사용자 목록을 먼저 읽는다.
        both = list(session.scalars(select(Bookmark.user_id).where(Bookmark.event_id == to_id)))
        if both:
            session.execute(delete(Bookmark).where(Bookmark.event_id == from_id, Bookmark.user_id.in_(both)))
        session.execute(update(Bookmark).where(Bookmark.event_id == from_id).values(event_id=to_id))

    def _save(self, item, sido_code, category_id, today):
        """목록 항목 하나를 저장한다.

        Returns:
            ("saved", id), ("updated", id), 또는 TourAPI에 같은 행사가 있으면 ("duplicate", 정보).
        """
        identifier = f"{ID_PREFIX}{item['mt20id']}"
        title = item.get("prfnm")
        if not title:
            raise BusinessException(ErrorCode.TOUR_SYNC_REQUIRED_FIELD, extra={"field": "prfnm"})
        start, end = _date(item.get("prfpdfrom"), "prfpdfrom"), _date(item.get("prfpdto"), "prfpdto")
        if start > end:
            raise BusinessException(ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"reason": "start_after_end"})

        with Session(self.engine) as session:
            row = session.scalar(select(Event).where(Event.tour_content_id == identifier))
            duplicate = find_tour_duplicate(session, title, item.get("fcltynm"), sido_code, start, end)
        detail = facility = None
        refresh = row is not None and row.id % DETAIL_REFRESH_DAYS == today.toordinal() % DETAIL_REFRESH_DAYS
        if duplicate is None and (row is None or refresh):
            # 네트워크 호출은 트랜잭션 밖에서 끝낸다. 새 공연이거나 갱신 차례일 때만 부른다.
            detail = self.api.performance(item["mt20id"])
            facility = self._facility(detail.get("mt10id"))

        try:
            with Session(self.engine) as session, session.begin():
                row = session.scalar(select(Event).where(Event.tour_content_id == identifier).with_for_update())
                if duplicate is not None:
                    result = {"id": item["mt20id"], "tour_event_id": duplicate.id, "removed": False}
                    # 먼저 저장된 KOPIS 공연이 나중에 TourAPI에 올라온 경우. 리뷰가 없을 때만 지운다
                    # (리뷰 FK는 CASCADE가 아니고 남의 리뷰를 지우면 안 된다).
                    if row is not None and not session.scalar(select(exists().where(Review.event_id == row.id))):
                        self._move_bookmarks(session, row.id, duplicate.id)
                        session.delete(row)
                        result["removed"] = True
                    return "duplicate", result
                status = "updated" if row is not None else "saved"
                if row is None:
                    # 상세를 받은 뒤 다른 수집이 먼저 저장했을 수 있다. 그때는 상세 없이 갱신만 한다.
                    row = Event(tour_content_id=identifier)
                    session.add(row)
                row.category_id, row.sido_code = category_id, sido_code
                row.title = _text(title, "title")
                row.start_date, row.end_date = start, end
                row.is_permanent = item.get("openrun") == "Y" or (end - start).days > 90
                row.venue_name = _text(item.get("fcltynm"), "venue_name")
                row.image_url = _text(item.get("poster"), "image_url")
                if detail is not None:
                    row.description = detail.get("sty")
                    row.play_time = _text(detail.get("dtguidance"), "play_time")
                    row.fee_text = detail.get("pcseguidance")
                    row.price, row.is_free = _fee(row.fee_text)
                    row.organizer = _text(detail.get("entrpsnmH") or detail.get("entrpsnmP"), "organizer")
                    row.homepage_url = _text(_homepage_url(detail.get("relateurl")), "homepage_url")
                    row.tour_modified_at = _modified(detail.get("updatedate"))
                if facility:
                    row.address = _text(facility.get("adres"), "address")
                    row.contact_phone = _text(facility.get("telno"), "contact_phone")
                    row.latitude = _coordinate(facility.get("la"), 90)
                    row.longitude = _coordinate(facility.get("lo"), 180)
                session.flush()
                return status, row.id
        except IntegrityError as error:
            raise BusinessException(ErrorCode.TOUR_SYNC_DB_CONFLICT) from error
        except DataError as error:
            raise BusinessException(ErrorCode.TOUR_SYNC_INVALID_DATA, extra={"reason": "database_value_rejected"}) from error

    def sync_performances(self, today=None):
        """KST 오늘부터 LOOKAHEAD_DAYS일 안에 열리는 공연을 수집한다.

        Returns:
            saved(새로 저장), updated(목록 값 갱신), skipped(장르·지역 미매핑), duplicates(TourAPI와
            겹쳐 저장하지 않거나 지운 건), failures(건별·목록 오류), complete(failures가 없으면 True).
        """
        today = today or datetime.now(KST).date()
        report = {"saved": 0, "updated": 0, "skipped": 0, "duplicates": [], "failures": [], "complete": False}
        with Session(self.engine) as session:
            sidos = dict(session.execute(select(Sido.name, Sido.code)).all())
            categories = dict(session.execute(select(Category.name, Category.id)).all())

        def fail(page, performance_id, error, extra=None):
            code = error.error_code if isinstance(error, BusinessException) else ErrorCode.TOUR_SYNC_DB_CONFLICT
            report["failures"].append({
                "page": page, "id": performance_id, "code": code.code, "reason": code.message,
                "extra": extra if extra is not None else getattr(error, "extra", None),
            })

        try:
            for page, items in self.api.iter_performances(today, today + timedelta(days=LOOKAHEAD_DAYS)):
                for item in items:
                    sido_code = sidos.get(item.get("area"))
                    category_id = categories.get(GENRE_CATEGORY.get(item.get("genrenm")))
                    # 해외 공연, 지역 미기재, 사전에 없는 장르는 넣지 않는다.
                    if not item.get("mt20id") or sido_code is None or category_id is None:
                        report["skipped"] += 1
                        continue
                    try:
                        status, result = self._save(item, sido_code, category_id, today)
                        if status == "duplicate":
                            report["duplicates"].append(result)
                        else:
                            report[status] += 1
                    except BusinessException as error:
                        fail(page, item["mt20id"], error)
                    except SQLAlchemyError as error:
                        fail(page, item["mt20id"], error, {"reason": "database_error", "error_type": type(error).__name__})
        except BusinessException as error:
            # 목록 조회가 실패하면 이후 페이지를 알 수 없어 중단한다.
            fail(None, None, error)
        report["complete"] = not report["failures"]
        return report
