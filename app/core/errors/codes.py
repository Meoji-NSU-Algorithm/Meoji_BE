"""API 오류 코드 정의. 각 멤버는 (HTTP 상태 코드, 기본 메시지)를 가진다.

멤버 이름이 그대로 응답의 code 문자열이 되므로 번호식이 아니라 이름만 보고 원인을 알 수 있게 짓는다.
상태 코드를 예외 클래스가 아닌 여기에 두기 때문에, 새 실패 케이스는 멤버만 추가하면 된다.
"""

from enum import Enum


class ErrorCode(Enum):
    """오류 코드 enum. 멤버 값은 (status_code, message)이다."""

    # --- COMMON ---
    # 필수값 누락, 형식 오류 등 도메인을 특정하기 애매한 요청 값 오류
    COMMON_INVALID_INPUT = (400, "요청 값이 올바르지 않습니다.")
    # 연결 장애, 풀 대기 초과, 일시적 잠금 충돌을 하나의 DB 사용 불가 오류로 묶는다.
    COMMON_DB_UNAVAILABLE = (503, "데이터베이스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")
    # 라우팅 단계의 HTTPException: 존재하지 않는 경로(404)와 허용되지 않는 메서드(405)
    COMMON_NOT_FOUND = (404, "요청한 경로를 찾을 수 없습니다.")
    COMMON_METHOD_NOT_ALLOWED = (405, "허용되지 않는 HTTP 메서드입니다.")
    # 위 두 경우 외의 HTTPException 폴백. 실제 상태 코드와 설명은 핸들러가 예외에서 가져온다.
    COMMON_HTTP_ERROR = (400, "요청을 처리할 수 없습니다.")

    # 예상하지 못한 서버 오류(코드 버그, 미처리 예외 등)의 최종 응답.
    # 원인은 로그에만 남기고 클라이언트에는 노출하지 않는다. (app/core/errors/handlers.py)
    COMMON_INTERNAL_ERROR = (500, "알 수 없는 서버 오류")

    # --- EVENT ---
    # 상세 조회 대상 행사나 리뷰 조회 대상 행사가 없을 때
    EVENT_NOT_FOUND = (404, "행사를 찾을 수 없습니다.")

    # --- TOUR API ---
    # 연결/HTTP/API 실패는 요청 실패로, 응답 구조/페이지 오류는 응답 오류로 묶는다.
    # 세부 원인은 BusinessException.extra의 reason에 기록한다.
    TOUR_API_KEY_MISSING = (500, "TOURAPI_KEY가 설정되지 않았습니다.")
    TOUR_API_REQUEST_FAILED = (502, "TourAPI 요청에 실패했습니다.")
    TOUR_API_INVALID_RESPONSE = (502, "TourAPI 응답이 올바르지 않습니다.")
    TOUR_FESTIVAL_INVALID_PERIOD = (400, "축제 조회 기간이 올바르지 않습니다.")

    # --- TOUR SYNC ---
    # 필드별 형식/범위/길이/분류 오류는 하나로 묶고 extra에 필드와 원인을 담는다.
    TOUR_SYNC_INVALID_DATA = (400, "축제 데이터가 올바르지 않습니다.")
    TOUR_SYNC_REQUIRED_FIELD = (400, "필수값이 비어 있습니다.")
    TOUR_SYNC_ID_MISMATCH = (400, "요청한 콘텐츠 ID와 응답이 다릅니다.")
    TOUR_SYNC_CONTENT_CHANGED = (409, "상세 수집 중 행사 정보가 삭제되었습니다.")
    TOUR_SYNC_DB_CONFLICT = (409, "DB 저장 중 무결성 충돌이 발생했습니다.")
    TOUR_SYNC_SEED_MISSING = (500, "카테고리·시도·태그 기준 데이터가 없습니다.")
    # 전체 수집은 끝까지 진행했지만 report.failures가 남은 경우.
    # 마지막 성공 시각은 갱신하지 않고, 실패한 content ID와 원래 오류 코드를 로그에 남긴다.
    TOUR_SYNC_INCOMPLETE = (500, "축제 데이터를 모두 갱신하지 못했습니다.")
    # 예약 스레드에서 DB 상태 조회·저장 등 예상 못한 예외가 난 경우.
    # traceback은 로그에만 남기고 다음 주기에 다시 시도한다.
    TOUR_SYNC_SCHEDULE_FAILED = (500, "정기 축제 갱신 중 오류가 발생했습니다.")

    # --- AUTH ---
    # 원인을 세분화하지 않은 일반 인증 실패. 토큰이 없는 경우에도 사용한다.
    AUTH_UNAUTHORIZED = (401, "인증에 실패했습니다.")

    # --- JWT ---
    # 유효기간(exp)이 지난 토큰. 프론트는 이 code를 보고 refresh 재발급을 시도하거나 재로그인시킨다.
    AUTH_TOKEN_EXPIRED = (401, "토큰이 만료되었습니다.")
    # 서명 불일치(위조), 형식 오류, 토큰 종류 불일치
    AUTH_TOKEN_INVALID = (401, "유효하지 않은 토큰입니다.")
    # TokenBlocklist에 등록된 토큰(로그아웃 또는 이미 사용한 refresh 토큰)
    AUTH_TOKEN_REVOKED = (401, "로그아웃된 토큰입니다.")

    # --- KAKAO ---
    # 인가 코드(code)로 카카오 토큰을 발급받지 못한 경우.
    # code는 일회용이고 약 10분만 유효해 만료/재사용이 가장 흔한 원인이다.
    # 프론트는 카카오 로그인을 처음부터 다시 시작해야 한다.
    KAKAO_TOKEN_REQUEST_FAILED = (401, "카카오 인가 코드가 유효하지 않습니다.")
    # 카카오 서버와 통신하지 못했거나(타임아웃/연결 실패) 예상 밖의 응답을 받은 경우
    KAKAO_API_UNAVAILABLE = (502, "카카오 서버와 통신할 수 없습니다.")
    # 사용자 정보에 필수 항목(이메일 등)이 없는 경우. 동의항목 미동의가 주된 원인이다.
    KAKAO_PROFILE_INVALID = (400, "카카오 계정 정보를 가져올 수 없습니다. 이메일 제공에 동의해주세요.")

    # --- USER ---
    # 토큰은 유효하지만 해당 id의 유저가 DB에 없는 경우(탈퇴 등)
    USER_NOT_FOUND = (404, "사용자를 찾을 수 없습니다.")
    # 같은 이메일을 다른 카카오 계정이 이미 사용 중인 경우
    USER_EMAIL_CONFLICT = (409, "이미 다른 계정에서 사용 중인 이메일입니다.")

    # --- REVIEW ---
    # 수정/삭제 대상 리뷰가 존재하지 않는 경우
    REVIEW_NOT_FOUND = (404, "리뷰를 찾을 수 없습니다.")
    # 리뷰 작성자가 아닌 사용자가 수정/삭제하려는 경우
    REVIEW_FORBIDDEN = (403, "리뷰를 수정하거나 삭제할 권한이 없습니다.")

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message

    @property
    def code(self) -> str:
        """응답의 code 값. enum 멤버 이름을 그대로 사용한다."""
        return self.name
