from enum import Enum

"""
    작성규칙
    오류 명시 = (상태코드, 오류 메세지)

    이후 필요할 때마다 여기에 한 줄씩 추가

    - 멤버 이름(예: AUTH_TOKEN_EXPIRED)이 그대로 프론트에 내려가는 code 문자열이 된다.
      그래서 AUTH_001 같은 번호식이 아니라, 이름만 봐도 무슨 에러인지 알 수 있게 짓는다.
    - status_code를 여기(ErrorCode)에 같이 넣어두는 이유: BusinessException은 클래스가
      단 하나뿐이라서, "이 에러가 몇 번 상태코드로 응답돼야 하는지"를 클래스가 아니라
      ErrorCode가 들고 있어야 한다. 새 도메인(카카오, 유저 등)이 추가돼도 새 클래스를
      만들 필요 없이 이 enum에 멤버만 추가하면 된다.
"""
class ErrorCode(Enum):
    # --- COMMON ---
    # 도메인을 특정하기 애매한 일반적인 요청 값 오류(필수값 누락, 형식 오류 등)에 사용.
    COMMON_INVALID_INPUT = (400, "요청 값이 올바르지 않습니다.")
    # 연결 장애·풀 대기 초과·일시적 잠금 충돌을 하나의 DB 사용 불가 오류로 묶는다.
    COMMON_DB_UNAVAILABLE = (503, "데이터베이스를 사용할 수 없습니다. 잠시 후 다시 시도해주세요.")

    # --- EVENT ---
    # 상세 ID가 없거나 목록·월간 인기 조회에 반환할 행사가 없을 때 사용한다.
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
    TOUR_SYNC_CONTENT_NOT_FOUND = (404, "목록을 먼저 저장해야 합니다.")
    TOUR_SYNC_CONTENT_CHANGED = (409, "상세 수집 중 행사 정보가 삭제되었습니다.")
    TOUR_SYNC_DB_CONFLICT = (409, "DB 저장 중 무결성 충돌이 발생했습니다.")
    TOUR_SYNC_SEED_MISSING = (500, "카테고리·시도·태그 기준 데이터가 없습니다.")
    # 전체 수집은 계속 진행했지만 report.failures가 남은 경우. 이때는 마지막
    # 성공 시각을 갱신하지 않고, 실패한 content ID와 원래 오류 코드를 로그에 남긴다.
    TOUR_SYNC_INCOMPLETE = (500, "축제 데이터를 모두 갱신하지 못했습니다.")
    # 예약 스레드에서 DB 상태 조회·저장 등 예상 못한 예외가 발생한 경우.
    # 상세 traceback은 로그에만 남기고 다음 주기에 다시 시도한다.
    TOUR_SYNC_SCHEDULE_FAILED = (500, "정기 축제 갱신 중 오류가 발생했습니다.")

    # --- AUTH ---
    # 로그인 자체가 안 됐거나 인증 수단이 아예 없는 등, 원인을 세분화하지 않은 일반 인증 실패.
    # (토큰이 "없는" 것과 "만료된" 것을 구분해야 하면 별도 ErrorCode를 추가해서 쓴다.)
    AUTH_UNAUTHORIZED = (401, "인증에 실패했습니다.")

    # --- JWT ---
    # access/refresh 토큰의 유효기간(exp)이 지나서 더 이상 사용할 수 없을 때.
    # 프론트에서는 이 code를 보고 리프레시 토큰으로 재발급을 시도하거나 재로그인시키면 된다.
    AUTH_TOKEN_EXPIRED = (401, "토큰이 만료되었습니다.")
    # 서명이 안 맞거나(위조), 형식이 깨진 토큰
    AUTH_TOKEN_INVALID = (401, "유효하지 않은 토큰입니다.")
    # 로그아웃 등으로 TokenBlocklist에 등록된 토큰
    AUTH_TOKEN_REVOKED = (401, "로그아웃된 토큰입니다.")

    # --- KAKAO ---
    # 프론트가 넘긴 인가 코드(code)로 카카오 토큰 발급에 실패한 경우.
    # code는 일회용 + 약 10분 유효라서, 만료/재사용이 가장 흔한 원인이다.
    # 프론트는 이 code를 받으면 카카오 로그인을 처음부터 다시 시작시키면 된다.
    KAKAO_TOKEN_REQUEST_FAILED = (401, "카카오 인가 코드가 유효하지 않습니다.")

    # --- USER ---
    # 토큰은 유효하지만 해당 id의 유저가 DB에 없는 경우 (탈퇴 등).
    USER_NOT_FOUND = (404, "사용자를 찾을 수 없습니다.")

    # --- INTERNAL_ERROR ---
    # BusinessException/HTTPException 어디에도 속하지 않는, 예상 못한 서버 내부 오류
    # (코드 버그, DB/외부 API 미처리 예외 등)에 사용. app/__init__.py의
    # @app.errorhandler(Exception)에서 이 코드로 항상 동일한 500 응답을 내려준다.
    # 실제 원인은 로그로만 남기고 클라이언트에는 구체적인 원인을 노출하지 않는다.
    COMMON_INTERNAL_ERROR = (500, "알 수 없는 서버 오류")

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message

    # --- REVIEW ---
    #
    # 리뷰 API에서 발생할 수 있는 예외 상황을 정의한다.
    # 리뷰 조회, 수정, 삭제 과정에서 발생하는 오류를
    # 공통 ErrorCode로 관리하여 일관된 응답을 반환할 수 있도록 한다.

    # 요청한 리뷰가 DB에 존재하지 않는 경우.
    # 리뷰 수정, 삭제 등 특정 리뷰를 대상으로 하는 요청에서 사용한다.
    REVIEW_NOT_FOUND = (404, "리뷰를 찾을 수 없습니다.")

    # 리뷰 작성자가 아닌 사용자가 해당 리뷰를 수정하거나 삭제하려는 경우.
    # 현재 사용자의 user_id와 리뷰의 user_id를 비교하여 권한을 확인한다.
    REVIEW_FORBIDDEN = (403, "리뷰를 수정하거나 삭제할 권한이 없습니다.")

    @property
    def code(self) -> str:
        # enum 멤버 이름(예: "AUTH_TOKEN_EXPIRED")을 그대로 응답의 code 값으로 사용.
        # BusinessException.error_code.code 로 접근해서 CommonResponse.error()에 전달된다.
        return self.name
