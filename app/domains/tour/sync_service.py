# 전국 TourAPI 축제를 events와 event_tags에 저장하는 서비스.
# 목록 한 건마다 상세 API 두 개를 먼저 조회하고, 한 트랜잭션 안에서
# 행사와 태그 연결을 저장한다. 실패 건은 롤백하되 다음 행사는 계속 처리한다.

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

# API 필드가 응답에 없으면 기존 값은 유지하고, 빈 문자열이면 NULL로 갱신한다.
# 오른쪽 컬럼의 최대 길이는 모델 메타데이터에서 검사한다.
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

# 사전은 검색 기능에서 사용할 키워드만 포함한다. 등록되지 않은 단어를 태그로
# 만들지 않아 재수집할 때 관계와 검색 결과가 예측 가능하다.
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


# TourAPI의 homepage에는 URL 외에 링크 태그, 설명, 여러 SNS 주소가 함께 올 수 있다.
# href가 있으면 실제 링크 대상을 사용하고, 없으면 문장에 처음 등장하는 주소를 쓴다.
HREF_PATTERN = re.compile(r"\bhref\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|(?<![\w@/])(?:[\w-]+\.)+[\w-]{2,}(?::\d+)?(?:[/?][^\s<>\"']*)?",
    re.I,
)


def _homepage_url(value):
    # HTML 엔티티를 먼저 풀어 href의 쿼리 문자열에 들어 있는 &도 원래대로 저장한다.
    # 프런트엔드가 그대로 링크로 사용할 수 있도록 http(s) URL 하나만 반환한다.
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
    # 원본에 유효한 웹 주소가 없다면 설명 문구 대신 NULL을 저장한다.
    return None


def _value(item, key):
    # API 문자열의 양끝 공백을 제거한다. 빈 문자열을 NULL로 바꾸는 일은
    # 컬럼별 유효성 검사와 함께 _assign()에서 처리한다.
    value = item.get(key)
    return value.strip() if isinstance(value, str) else value


def _date(value, field):
    # API의 YYYYMMDD를 DB DATE로 변환한다. 형식과 실제 날짜를 모두 검증한다.
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
    # modifiedtime은 API가 전달한 14자리 날짜/시간을 DB DATETIME으로 바꾼다.
    # created_at/updated_at과 달리 원본 수정 시각을 그대로 저장한다.
    text = str(value)
    if not re.fullmatch(r"[0-9]{14}", text):
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": "modifiedtime", "reason": "invalid_datetime"},
        )
    try:
        # API 원본의 한국 현지 시각을 보존한다. DATETIME은 시간대 정보를 갖지 않는다.
        return datetime.strptime(text, "%Y%m%d%H%M%S")
    except ValueError as error:
        raise BusinessException(
            ErrorCode.TOUR_SYNC_INVALID_DATA,
            extra={"field": "modifiedtime", "reason": "invalid_datetime"},
        ) from error


def _coordinate(value, field, bound):
    # 지도 좌표는 float 오차를 피하기 위해 Decimal로 읽는다.
    # 경도는 ±180, 위도는 ±90 범위만 허용한다.
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
    # events의 DECIMAL(10,7)은 정수부가 최대 세 자리다.
    return number


def _category(code):
    # 참조 seed.sql의 코드 변환 순서. EV010500은 EV01의 하위 코드이므로
    # 일반 축제보다 먼저 판별해야 계절행사로 분류된다.
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
    # 대표 가격은 원 단위 금액의 최소값이다. 무료 표시 또는 0원만 안내하면 무료다.
    # 시간이나 할인 조건처럼 금액을 알 수 없는 문구는 NULL로 두어 추측하지 않는다.
    if not fee_text:
        return None, None
    if re.search(r"무료|입장료\s*없음", fee_text) and not re.search(r"유료|\d[\d,]*\s*원", fee_text):
        return 0, True
    amounts = [int(raw.replace(",", "")) for raw in re.findall(r"(\d[\d,]*)\s*원", fee_text)]
    if amounts:
        price = min(amounts)
        # price 컬럼은 signed INT다. DB에서 범위 오류가 나기 전에 해당 항목을 거부한다.
        if price > 2_147_483_647:
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"field": "usetimefestival", "reason": "price_out_of_range"},
            )
        # 0원만 안내한 행사는 무료다. 양수 금액이나 유료 안내가 함께 있으면 유료로 둔다.
        return price, not any(amounts) and "유료" not in fee_text
    if "유료" in fee_text:
        return None, False
    return None, None


class TourSyncService:
    # 같은 TourAPI contentid가 다시 들어오면 기존 Event 행을 갱신한다.

    def __init__(self, api=None, engine=None):
        self._api = api  # 테스트에서는 가짜 API를 전달할 수 있음
        self.engine = engine if engine is not None else db.engine  # 기본은 Flask 앱의 DB

    @property
    def api(self):
        # 실제 API 클라이언트는 처음 호출할 때 만들어 설정 누락도 그때 검사한다.
        if self._api is None:
            self._api = TourAPI()
        return self._api

    @staticmethod
    def _identity(item, requested=None):
        # 축제 타입 15만 저장하며, 요청한 ID와 응답 ID가 다르면 다른 행사
        # 정보가 섞일 수 있으므로 DB 작업 전에 거부한다.
        if not isinstance(item, dict):
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"reason": "item_not_object"},
            )
        # None·객체·배열을 문자열로 바꾸면 잘못된 ID가 정상 값처럼 저장될 수 있다.
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
        # TEXT_FIELDS의 API 필드만 Event 컬럼에 반영한다. 미전달 필드는
        # 기존 값 유지, 명시적으로 전달된 빈 값은 NULL로 갱신한다.
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
                # URL 이외의 태그·문구·두 번째 링크를 DB에 남기지 않는다.
                value = _homepage_url(value)
            # 모델 컬럼의 nullable/길이를 그대로 사용해 DB 오류 전에 검증한다.
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
            # 검증을 통과한 필드만 행에 반영한다.
            setattr(row, target, value)

    def _save(self, list_item, common, intro, require_existing=False):
        # 목록과 두 상세가 모두 같은 contentid의 축제인지 먼저 검증한다.
        identifier = self._identity(list_item)
        for detail in (common, intro):
            if not isinstance(detail, dict):
                raise BusinessException(
                    ErrorCode.TOUR_SYNC_INVALID_DATA,
                    extra={"reason": "detail_not_object"},
                )
            # 상세 응답에 ID가 없어도 타입이 있다면 검증한다. ID 생략을 이유로
            # 축제 이외의 콘텐츠 타입이 검증을 건너뛰고 저장되지 않도록 한다.
            self._identity(
                {
                    "contentid": detail.get("contentid", identifier),
                    "contenttypeid": detail.get("contenttypeid", "15"),
                },
                identifier,
            )

        # 같은 필드는 상세 응답을 우선한다. 아예 없는 필드는 _assign이 건너뛴다.
        merged = {**list_item, **common, **intro}
        # 상세 응답의 빈 날짜가 목록의 유효한 값을 덮지 않도록 한다.
        for key in ("eventstartdate", "eventenddate"):
            if not _value(merged, key) and _value(list_item, key):
                merged[key] = list_item[key]
        try:
            # 한 행사와 태그의 변경을 하나의 트랜잭션으로 묶는다.
            # 아래 어느 검증이나 DB 작업이 실패해도 이 행사만 롤백된다.
            with Session(self.engine) as session, session.begin():
                # 동일 콘텐츠를 재수집하면 행 잠금을 잡고 수정한다.
                row = session.scalar(
                    select(Event)
                    .where(Event.tour_content_id == identifier)
                    .with_for_update()
                )
                if row is None:
                    # 상세 갱신 도중 원본 행이 삭제됐다면 목록 없이 새 행을 만들지 않는다.
                    if require_existing:
                        raise BusinessException(ErrorCode.TOUR_SYNC_CONTENT_CHANGED)
                    row = Event(tour_content_id=identifier)

                # 미전달 필드는 행 잠금을 잡은 뒤 읽은 최신 값으로 유지한다.
                # API 호출 전에 복사한 값을 사용하면 다른 요청의 갱신을 덮을 수 있다.
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
                # FK 기준값은 마이그레이션이 시드한다. 모르는 코드를 임의로 만들지 않는다.
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
                # 날짜는 문자열 컬럼과 달리 DATE로 변환하고 역전 여부를 확인한다.
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
                row.is_permanent = (row.end_date - row.start_date).days > 90  # 90일 초과는 상설 표시
                for source, target, bound in (("mapy", "latitude", 90), ("mapx", "longitude", 180)):
                    if source in merged:
                        setattr(row, target, _coordinate(_value(merged, source), source, bound))
                if "modifiedtime" in merged:
                    row.tour_modified_at = (
                        _modified(merged["modifiedtime"])
                        if _value(merged, "modifiedtime")
                        else None
                    )
                # 요금이 새로 왔을 때만 대표 가격/무료 여부를 다시 계산한다.
                if "usetimefestival" in merged:
                    row.price, row.is_free = _fee(row.fee_text)
                # 태그는 소개글을 실제로 받은 경우에만 교체한다.
                if "overview" in merged:
                    wanted = [name for name in TAG_KEYWORDS if name in (row.description or "")]
                    tags = list(session.scalars(select(Tag).where(Tag.name.in_(wanted)))) if wanted else []
                    if len(tags) != len(wanted):
                        raise BusinessException(
                            ErrorCode.TOUR_SYNC_SEED_MISSING,
                            extra={"tags": wanted},
                        )
                    row.tags = tags  # 기존 연결을 새 소개글에 맞게 교체
                # INSERT/UPDATE 및 태그 관계 변경을 이번 트랜잭션 안에서 실행한다.
                session.flush()
                return row.id
        except IntegrityError as error:
            raise BusinessException(ErrorCode.TOUR_SYNC_DB_CONFLICT) from error
        except DataError as error:
            # DB가 거부한 길이·범위 오류도 한 건의 검증 실패로 기록해 다음 항목을 수집한다.
            raise BusinessException(
                ErrorCode.TOUR_SYNC_INVALID_DATA,
                extra={"reason": "database_value_rejected"},
            ) from error

    def sync_festivals(self, start_date=None, end_date=None, today=None):
        # 전국 목록의 모든 페이지를 돌며 상세까지 수집한다.
        # saved는 성공 건수, failures는 건별 오류, complete는 전체 성공 여부다.
        # 한 번의 수집 내내 같은 한국 날짜를 사용해 자정 전후의 판단 차이를 막는다.
        today = today or datetime.now(KST).date()
        if start_date is None and end_date is None:
            # API 조회 범위는 누락 방지를 위해 오늘보다 7일 앞에서 시작한다.
            # 받아온 행사는 종료일이 지나도 DB에서 삭제하지 않고 계속 보관한다.
            # 화면 목록에서 지난 행사를 제외하는 일은 EventService가 맡는다.
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
                        # API 조회는 트랜잭션 전에 끝낸다. 네트워크 지연 동안
                        # DB 트랜잭션과 행 잠금을 길게 유지하지 않기 위해서다.
                        identifier = self._identity(item)
                        common = self.api.festival_common(identifier)
                        intro = self.api.festival_intro(identifier)
                        # 지난 행사도 새로 저장하거나 기존 행을 갱신한다.
                        # 리뷰가 달린 행사 역시 DB에 남기므로 리뷰도 유지된다.
                        self._save(item, common, intro)
                        report["saved"] += 1
                    except BusinessException as error:
                        # 건별 실패만 기록하고 다음 축제 수집은 계속한다.
                        report["failures"].append({
                            "page": page,
                            "content_id": identifier,
                            "code": error.error_code.code,
                            "reason": error.message,
                            "extra": error.extra,
                        })
        except BusinessException as error:
            # 목록 페이지 자체가 실패하면 이후 페이지를 알 수 없으므로 종료한다.
            report["failures"].append({
                "page": None,
                "content_id": None,
                "code": error.error_code.code,
                "reason": error.message,
                "extra": error.extra,
            })
        report["complete"] = not report["failures"]
        # 전체 성공 여부는 예약 작업의 다음 실행 시각 기록에만 사용한다.
        # 실패하거나 목록에서 더 이상 보이지 않는 행사도 여기서 삭제하지 않는다.
        return report
