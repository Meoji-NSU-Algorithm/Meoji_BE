"""TourAPI 전국 축제를 events와 event_tags에 저장하는 수집 서비스.

목록의 항목마다 상세 API 두 개를 먼저 조회한 뒤, 한 트랜잭션에서 행사와 태그
연결을 저장한다. 실패한 건은 롤백하고 다음 건을 계속 처리한다.
"""

import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from html import unescape
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.core.time import KST
from app.domains.events.models import Category, Event, Sido, Tag
from app.domains.tour.client import TourAPI

# TourAPI 필드 -> Event 컬럼. 응답에 필드가 없으면 기존 값을 유지하고 빈 문자열이면 NULL로 갱신한다.
TEXT_FIELDS = {
    "title": "title",
    "overview": "description",
    "playtime": "play_time",
    "eventplace": "venue_name",
    "addr1": "address",
    "addr2": "address_detail",
    "firstimage": "image_url",
    "firstimage2": "thumbnail_url",
    "usetimefestival": "fee_text",
    "sponsor1": "organizer",
    "tel": "contact_phone",
    "homepage": "homepage_url",
    "lclsSystm3": "lcls_code",
}

# 소개글에서 찾을 태그 사전. 여기 없는 단어는 태그로 만들지 않는다.
TAG_KEYWORDS = (
    "불꽃놀이",
    "푸드트럭",
    "야간",
    "체험",
    "가족",
    "공연",
    "전시",
    "음악",
    "꽃",
    "먹거리",
)


# homepage에는 URL 외에 <a> 태그, 설명 문구, 여러 주소가 섞여 올 수 있다.
# href가 있으면 그 값을, 없으면 처음 나오는 주소를 쓴다.
HREF_PATTERN = re.compile(r"\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|(?<![\w:/@])//[^\s<>\"']+|(?<![\w@/])(?:[\w-]+\.)+[\w-]{2,}(?::\d+)?(?:[/?][^\s<>\"']*)?",
    re.I,
)


def _homepage_url(value):
    """homepage 원문에서 http(s) URL 하나를 뽑아 반환한다. 유효한 주소가 없으면 None이다."""
    # HTML 엔티티를 먼저 풀어 href 쿼리 문자열의 &amp;를 &로 복원한다.
    if not value:
        return None
    text = unescape(value)
    href = HREF_PATTERN.search(text)
    candidates = ([next(part for part in href.groups() if part is not None)] if href else [])
    candidates.extend(match.group() for match in URL_PATTERN.finditer(text))
    for candidate in candidates:
        candidate = candidate.strip().rstrip(".,;:!?)]}")
        if any(char.isspace() for char in candidate):
            continue
        if candidate.startswith("//"):
            candidate = "https:" + candidate
        elif not re.match(r"https?://", candidate, re.I):
            candidate = "https://" + candidate
        try:
            parsed = urlsplit(candidate)
            if (
                parsed.scheme.lower() in ("http", "https")
                and parsed.hostname
                and "." in parsed.hostname
                and not parsed.hostname.startswith("httpwww.")
                and not parsed.username
                and not parsed.password
            ):
                parsed.port  # 잘못된 포트 표기는 URL로 저장하지 않는다.
                return candidate
        except ValueError:
            continue
    return None


def _value(item, key):
    """문자열이면 양끝 공백을 제거한다. 빈 문자열의 NULL 처리는 _assign()이 한다."""
    value = item.get(key)
    return value.strip() if isinstance(value, str) else value


def _date(value, field):
    """YYYYMMDD 문자열을 date로 바꾼다. 형식이나 실제 날짜가 틀리면 TOUR_SYNC_INVALID_DATA."""
    text = str(value)
    if not re.fullmatch(r"[0-9]{8}", text):
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": field, "reason": "invalid_date"},
        )
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError as error:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": field, "reason": "invalid_date"},
        ) from error


def _modified(value):
    """modifiedtime(YYYYMMDDHHMMSS)을 datetime으로 바꾼다. 형식이 틀리면 TOUR_SYNC_INVALID_DATA."""
    text = str(value)
    if not re.fullmatch(r"[0-9]{14}", text):
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": "modifiedtime", "reason": "invalid_datetime"},
        )
    try:
        # 시간대 변환 없이 API의 한국 시각을 그대로 저장한다.
        return datetime.strptime(text, "%Y%m%d%H%M%S")
    except ValueError as error:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": "modifiedtime", "reason": "invalid_datetime"},
        ) from error


def _coordinate(value, field, bound):
    """좌표 문자열을 Decimal로 바꾼다. 비어 있으면 None, 형식이나 범위(±bound) 오류는 TOUR_SYNC_INVALID_DATA."""
    # float 오차를 피하려고 Decimal을 쓴다.
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": field, "reason": "invalid_coordinate"},
        ) from error
    if not number.is_finite() or abs(number) > bound:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": field, "reason": "coordinate_out_of_range"},
        )
    # 위도 ±90, 경도 ±180이면 DECIMAL(10,7)의 정수부 3자리에 들어간다.
    return number


def _category(code):
    """lclsSystm3 코드를 카테고리 이름으로 바꾼다. 모르는 코드는 TOUR_SYNC_INVALID_DATA."""
    # EV010500은 EV01의 하위 코드이므로 계절행사를 일반 축제보다 먼저 판별해야 한다.
    if code == "EV010500":
        return "계절행사"
    if code.startswith("EV01"):
        return "축제"
    if code.startswith("EV02"):
        return "공연"
    if code == "EV030100":
        return "전시"
    if code.startswith("EV03"):
        return "체험"
    raise BusinessException(
        ErrorCode.TOUR_SYNC_INVALID_DATA,
        extra={"field": "lclsSystm3", "reason": "unknown_category", "value": code},
    )


def _fee(fee_text):
    """요금 문구에서 (대표 금액, 무료 여부)를 추정한다.

    금액이 여럿이면 최소값을 쓰고, 무료 표기 또는 0원만 있으면 무료로 본다.
    판단할 수 없는 문구는 추측하지 않고 해당 값을 None으로 둔다.
    """
    if not fee_text:
        return None, None
    if re.search(r"무료|입장료\s*없음", fee_text) and not re.search(r"유료|\d[\d,]*\s*원", fee_text):
        return 0, True
    amounts = [int(raw.replace(",", "")) for raw in re.findall(r"(\d[\d,]*)\s*원", fee_text)]
    if amounts:
        price = min(amounts)
        # price 컬럼이 signed INT라서 넘치면 DB 오류 전에 거부한다.
        if price > 2_147_483_647:
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"field": "usetimefestival", "reason": "price_out_of_range"},
            )
        # 0원만 있으면 무료, 양수 금액이나 "유료" 표기가 함께 있으면 유료.
        return price, not any(amounts) and "유료" not in fee_text
    if "유료" in fee_text:
        return None, False
    return None, None


class TourSyncService:
    """TourAPI 축제를 Event로 저장한다. 같은 contentid는 기존 행을 갱신한다."""

    def __init__(self, api=None, engine=None):
        """api와 engine은 테스트 주입용이다. 생략하면 실제 TourAPI와 db.engine을 쓴다."""
        self._api = api
        self.engine = engine if engine is not None else db.engine

    @property
    def api(self):
        """TourAPI 클라이언트. 처음 접근할 때 만들어 키 누락도 그때 검사한다."""
        if self._api is None:
            self._api = TourAPI()
        return self._api

    @staticmethod
    def _identity(item, requested=None):
        """item의 contentid를 검증해 반환한다.

        축제(contenttypeid 15)만 허용하고, requested가 있으면 응답 ID와 일치해야 한다.
        다른 행사의 정보가 섞이지 않도록 DB 작업 전에 거부한다.
        """
        if not isinstance(item, dict):
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"reason": "item_not_object"},
            )
        # None, 객체, 배열을 str()로 바꾸면 잘못된 ID가 정상 값처럼 통과한다.
        raw_id = item.get("contentid")
        identifier = (
            str(raw_id).strip()
            if isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool)
            else ""
        )
        if not identifier or len(identifier) > 20:
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"field": "contentid", "reason": "invalid_id"},
            )
        if requested is not None and identifier != requested:
            raise BusinessException(ErrorCode.TOUR_SYNC_ID_MISMATCH)
        if "contenttypeid" in item and str(item["contenttypeid"]) != "15":
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"field": "contenttypeid", "reason": "not_festival"},
            )
        return identifier

    @staticmethod
    def _assign(row, payload):
        """TEXT_FIELDS에 정의된 필드를 검증해 Event 컬럼에 반영한다."""
        for source, target in TEXT_FIELDS.items():
            if source not in payload:
                continue
            value = _value(payload, source)
            if value is not None and not isinstance(value, (str, int, float)):
                raise BusinessException(
                    ErrorCode.TOUR_SYNC_INVALID_DATA,
                    extra={"field": source, "reason": "invalid_field_type"},
                )
            value = str(value) if value is not None else None
            if value == "":
                value = None
            if source == "homepage":
                value = _homepage_url(value)
            # 모델 컬럼의 nullable/길이로 DB 오류 전에 검증한다.
            column = Event.__table__.columns[target]
            if value is None and not column.nullable:
                raise BusinessException(
                    ErrorCode.TOUR_SYNC_REQUIRED_FIELD,
                    extra={"field": source},
                )
            limit = getattr(column.type, "length", None)
            if value is not None and limit and len(value) > limit:
                raise BusinessException(
                    ErrorCode.TOUR_SYNC_INVALID_DATA,
                    extra={"field": source, "reason": "field_too_long", "limit": limit},
                )
            setattr(row, target, value)

    def _save(self, list_item, common, intro, require_existing=False):
        """목록과 상세 응답을 하나의 트랜잭션에서 Event와 태그로 저장하고 event id를 반환한다.

        Args:
            require_existing: True이면 기존 행이 없을 때 새로 만들지 않고
                TOUR_SYNC_CONTENT_CHANGED를 발생시킨다.

        Raises:
            BusinessException: 검증 실패, 기준 데이터(카테고리·시도·태그) 누락,
                DB 무결성 충돌 등 TOUR_SYNC_* 오류. 발생하면 이 건만 롤백된다.
        """
        # 목록과 두 상세가 같은 contentid의 축제인지 먼저 확인한다.
        identifier = self._identity(list_item)
        for detail in (common, intro):
            if not isinstance(detail, dict):
                raise BusinessException(
                    ErrorCode.TOUR_SYNC_INVALID_DATA,
                    extra={"reason": "detail_not_object"},
                )
            # 상세에 ID나 타입이 없으면 기대값으로 대체해 검증한다.
            # 필드 생략으로 다른 콘텐츠 타입이 검증을 우회하지 못하게 한다.
            self._identity(
                {
                    "contentid": detail.get("contentid", identifier),
                    "contenttypeid": detail.get("contenttypeid", "15"),
                },
                identifier,
            )

        # 같은 필드는 상세(common, intro)가 목록보다 우선한다.
        merged = {**list_item, **common, **intro}
        # 상세의 빈 날짜가 목록의 유효한 값을 덮어쓰지 않게 한다.
        for key in ("eventstartdate", "eventenddate"):
            if not _value(merged, key) and _value(list_item, key):
                merged[key] = list_item[key]
        try:
            # 행사와 태그 변경을 한 트랜잭션으로 묶어 실패 시 이 건만 롤백한다.
            with Session(self.engine) as session, session.begin():
                # 같은 행사를 동시에 갱신하지 않도록 행을 잠근다.
                row = session.scalar(
                    select(Event)
                    .where(Event.tour_content_id == identifier)
                    .with_for_update()
                )
                if row is None:
                    # 상세만 갱신하는 경로에서 행이 중간에 삭제됐다면 새로 만들지 않는다.
                    if require_existing:
                        raise BusinessException(ErrorCode.TOUR_SYNC_CONTENT_CHANGED)
                    row = Event(tour_content_id=identifier)

                # 응답에 없는 값은 잠금 후 읽은 최신 행 값으로 대체한다. API 호출 전에
                # 읽어 둔 값을 쓰면 그사이의 다른 갱신을 덮어쓸 수 있다.
                code = str(
                    _value(merged, "lclsSystm3")
                    or _value(list_item, "lclsSystm3")
                    or row.lcls_code or ""
                ).strip()
                # lDongRegnCd는 세종처럼 5자리로 올 수 있으므로 앞 두 자리만 사용한다.
                sido_code = str(
                    _value(merged, "lDongRegnCd")
                    or _value(list_item, "lDongRegnCd")
                    or row.sido_code or ""
                )[:2]
                if not re.fullmatch(r"[0-9]{2}", sido_code):
                    raise BusinessException(
                        ErrorCode.TOUR_SYNC_INVALID_DATA,
                        extra={"field": "lDongRegnCd", "reason": "invalid_sido", "value": sido_code},
                    )
                category_name = _category(code)
                merged["lclsSystm3"] = code
                # 기준 데이터는 마이그레이션이 시드한다. 없으면 임의로 만들지 않고 실패시킨다.
                category = session.scalar(select(Category).where(Category.name == category_name))
                sido = session.get(Sido, sido_code)
                if category is None or sido is None:
                    raise BusinessException(
                        ErrorCode.TOUR_SYNC_SEED_MISSING,
                        extra={"category": category_name, "sido_code": sido_code},
                    )
                session.add(row)
                row.category_id, row.sido_code = category.id, sido_code
                self._assign(row, merged)
                if not row.title:
                    raise BusinessException(
                        ErrorCode.TOUR_SYNC_REQUIRED_FIELD,
                        extra={"field": "title"},
                    )
                for source, target in (("eventstartdate", "start_date"), ("eventenddate", "end_date")):
                    if source in merged:
                        setattr(row, target, _date(merged[source], source))
                if row.start_date is None or row.end_date is None:
                    raise BusinessException(
                        ErrorCode.TOUR_SYNC_REQUIRED_FIELD,
                        extra={"fields": ["eventstartdate", "eventenddate"]},
                    )
                if row.start_date > row.end_date:
                    raise BusinessException(
                        ErrorCode.TOUR_SYNC_INVALID_DATA,
                        extra={"reason": "start_after_end"},
                    )
                row.is_permanent = (row.end_date - row.start_date).days > 90  # 90일 초과는 상설
                for source, target, bound in (("mapy", "latitude", 90), ("mapx", "longitude", 180)):
                    if source in merged:
                        setattr(row, target, _coordinate(_value(merged, source), source, bound))
                if "modifiedtime" in merged:
                    row.tour_modified_at = (
                        _modified(merged["modifiedtime"])
                        if _value(merged, "modifiedtime")
                        else None
                    )
                # 요금이 응답에 있을 때만 대표 가격/무료 여부를 다시 계산한다.
                if "usetimefestival" in merged:
                    row.price, row.is_free = _fee(row.fee_text)
                # 소개글이 응답에 있을 때만 태그를 다시 계산해 교체한다.
                if "overview" in merged:
                    wanted = [name for name in TAG_KEYWORDS if name in (row.description or "")]
                    tags = list(session.scalars(select(Tag).where(Tag.name.in_(wanted)))) if wanted else []
                    if len(tags) != len(wanted):
                        raise BusinessException(
                            ErrorCode.TOUR_SYNC_SEED_MISSING,
                            extra={"tags": wanted},
                        )
                    row.tags = tags
                # 커밋 전에 SQL을 실행해 DB 오류를 아래 except에서 변환한다.
                session.flush()
                return row.id
        except IntegrityError as error:
            raise BusinessException(ErrorCode.TOUR_SYNC_DB_CONFLICT) from error
        except DataError as error:
            # DB가 거부한 길이·범위 오류도 이 건만의 실패로 처리해 다음 항목을 계속 수집한다.
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"reason": "database_value_rejected"},
            ) from error

    def sync_festivals(self, start_date=None, end_date=None, today=None):
        """전국 축제 목록을 모든 페이지 순회하며 상세와 함께 저장한다.

        기간을 생략하면 KST 기준 7일 전부터 수집한다. 지난 행사도 삭제하지 않고
        보관하며, 목록 API에서만 숨긴다.

        Returns:
            saved(저장 건수), failures(건별·목록 페이지 오류 목록), complete(failures가
            비어 있으면 True). complete가 True일 때만 전체 성공으로 취급한다.
        """
        # 수집 내내 같은 날짜를 쓰기 위해 한 번만 계산한다.
        today = today or datetime.now(KST).date()
        if start_date is None and end_date is None:
            # 최근 등록·수정된 행사를 놓치지 않도록 7일 전부터 조회한다.
            start_date = (today - timedelta(days=7)).strftime("%Y%m%d")
        report = {
            "saved": 0,
            "failures": [],
            "complete": False,
        }
        try:
            for page, items in self.api.iter_festivals(start_date, end_date):
                for item in items:
                    identifier = item.get("contentid") if isinstance(item, dict) else None
                    try:
                        # 네트워크 호출을 트랜잭션 밖에서 끝내 행 잠금을 오래 쥐지 않는다.
                        identifier = self._identity(item)
                        common = self.api.festival_common(identifier)
                        intro = self.api.festival_intro(identifier)
                        self._save(item, common, intro)
                        report["saved"] += 1
                    except BusinessException as error:
                        # 건별 실패는 기록만 하고 다음 항목을 계속 처리한다.
                        report["failures"].append({
                            "page": page,
                            "content_id": identifier,
                            "code": error.error_code.code,
                            "reason": error.message,
                            "extra": error.extra,
                        })
        except BusinessException as error:
            # 목록 조회가 실패하면 이후 페이지를 알 수 없어 수집을 중단한다.
            report["failures"].append({
                "page": None,
                "content_id": None,
                "code": error.error_code.code,
                "reason": error.message,
                "extra": error.extra,
            })
        report["complete"] = not report["failures"]
        # 목록에서 사라진 행사도 여기서 삭제하지 않는다.
        return report
