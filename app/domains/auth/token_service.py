# 우리 서비스 JWT의 발급/재발급/폐기만 담당하는 서비스.
# 유저 생성이나 카카오 통신은 전혀 모른다. "유저 id를 받아 토큰을 만들고, 토큰을 폐기"하는 일만 한다.
#
# [JWT 기본 개념]
#   - access_token : API를 호출할 때마다 헤더에 넣는 토큰. 유효기간이 짧다(1시간, app/core/config.py).
#                    탈취되더라도 피해 시간을 줄이기 위해 짧게 둔다.
#   - refresh_token: access_token이 만료됐을 때 새 토큰을 받기 위한 토큰. 유효기간이 길다(14일).
#                    /api/auth/refresh 에서만 사용한다.
#
# [토큰 payload(내용물)에 들어있는 주요 값 = 클레임]
#   - sub  : 토큰 주인(identity). 우리는 유저 id를 문자열로 넣는다. 예: "1"
#   - jti  : 토큰마다 자동으로 붙는 고유 ID(UUID). 로그아웃/폐기 시 이 값을 블록리스트에 저장한다.
#   - type : "access" 또는 "refresh". 토큰 종류 구분용.
#   - exp  : 만료 시각
#
# [폐기(로그아웃)는 어떻게 하나?]
#   JWT는 서버에 저장하지 않는 "무상태" 토큰이라 서버가 강제로 만료시킬 수 없다.
#   그래서 폐기할 토큰의 jti를 TokenBlocklist 테이블에 저장하고, 요청이 올 때마다
#   app/core/jwt_callbacks.py의 check_if_token_revoked가 "이 jti가 블록리스트에 있나?"를 확인해서 거부한다.
from flask_jwt_extended import create_access_token, create_refresh_token, decode_token

from app.core.errors import BusinessException, ErrorCode
from app.core.extensions import db
from app.domains.auth.models import TokenBlocklist


def issue_tokens(user_id: int) -> dict:
    """유저 id로 우리 서비스의 access/refresh 토큰 쌍을 발급한다.

    로그인(auth_service.login_with_kakao)과 재발급(rotate_refresh_token)에서 같이 쓴다.
    반환값: {"access_token": "eyJ...", "refresh_token": "eyJ..."}
    """
    # Flask-JWT-Extended 4.7+는 sub(identity)가 문자열이어야 한다.
    # 숫자를 그대로 넣으면 토큰 검증 시 에러가 난다. 꺼내 쓸 때는 int()로 되돌린다.
    identity = str(user_id)
    # 서명에는 app/core/config.py의 JWT_SECRET_KEY, 만료시간에는 JWT_ACCESS/REFRESH_TOKEN_EXPIRES가 자동으로 쓰인다.
    return {
        "access_token": create_access_token(identity=identity),
        "refresh_token": create_refresh_token(identity=identity),
    }

# PyCharm 오탐 경고 끄기: TokenBlocklist(jti=...)에 "예기치 않은 인수" 경고가 뜨지만 코드는 정상이다.
#   (이유는 app/domains/users/service.py의 get_or_create_kakao_user 위 주석 참고)
# noinspection PyArgumentList
def rotate_refresh_token(refresh_payload: dict) -> dict:
    """사용한 refresh 토큰은 폐기하고 새 토큰 쌍을 발급한다 (Refresh Token Rotation).

    [Refresh Token Rotation이란?]
        refresh 토큰은 14일짜리라 탈취되면 오랫동안 악용될 수 있다.
        그래서 refresh 토큰은 "한 번 쓰면 버리는 일회용"으로 만든다.
        /refresh를 호출할 때마다 쓴 토큰은 블록리스트에 넣고, 새 refresh 토큰을 준다.
        → 공격자가 훔친 토큰을 쓰든 진짜 사용자가 먼저 쓰든, 나중에 쓰는 쪽은
          401 AUTH_TOKEN_REVOKED를 받게 되어 적어도 재사용이 차단된다.

    refresh_payload: 이미 @jwt_required(refresh=True)로 검증된 refresh 토큰의 내용물
    """
    # @jwt_required(refresh=True)가 이미 "블록리스트에 없는 토큰"임을 확인했으므로
    # 중복 저장 걱정 없이 바로 추가한다.
    db.session.add(TokenBlocklist(jti=refresh_payload["jti"]))
    # 새 토큰을 주기 전에 먼저 폐기를 DB에 확정한다.
    db.session.commit()
    # sub는 문자열 유저 id → issue_tokens가 받는 int로 변환
    return issue_tokens(int(refresh_payload["sub"]))


# PyCharm 오탐 경고 끄기: TokenBlocklist(jti=...)에 "예기치 않은 인수" 경고가 뜨지만 코드는 정상이다.
#   (이유는 app/domains/users/service.py의 get_or_create_kakao_user 위 주석 참고)
# noinspection PyArgumentList
def revoke_tokens(access_payload: dict, refresh_token: str) -> None:
    """로그아웃: access(헤더)와 refresh(body)를 둘 다 블록리스트에 등록한다.

    access_payload: 헤더의 access 토큰 내용물. @jwt_required()가 이미 검증을 끝낸 상태.
    refresh_token : body로 받은 refresh 토큰 "문자열". 아무도 검증하지 않았으므로 여기서 직접 검증한다.
    """
    # decode_token(): 토큰 문자열을 해석해서 payload dict로 바꾼다. 이때 서명도 검증한다.
    #   - allow_expired=True: 이미 만료된 refresh 토큰으로 로그아웃해도 에러 없이 처리한다.
    #     (어차피 만료된 토큰이라 폐기해도 손해가 없고, 사용자는 로그아웃에 실패하면 안 되니까)
    #   - 위조되거나 깨진 토큰이면 예외를 던진다. 여기서 try/except로 잡지 않아도
    #     Flask-JWT-Extended가 jwt.init_app() 때 앱에 등록해 둔 핸들러가 받아서
    #     app/core/jwt_callbacks.py의 invalid_token_callback → 401 AUTH_TOKEN_INVALID로 응답한다.
    #   - 주의: decode_token()은 블록리스트는 확인하지 않는다. (그래서 아래에서 중복 체크를 한다)
    refresh_payload = decode_token(refresh_token, allow_expired=True)

    # 서명은 정상이라 라이브러리는 통과시키지만, 우리 서비스 입장에서는 잘못된 요청인 경우를 직접 막는다.
    #   - type != "refresh": refresh 자리에 access 토큰을 넣은 경우
    #   - sub가 다름      : 다른 사람의 refresh 토큰을 넣은 경우 (남의 토큰을 폐기시키는 장난 방지)
    if refresh_payload.get("type") != "refresh" or refresh_payload["sub"] != access_payload["sub"]:
        raise BusinessException(ErrorCode.AUTH_TOKEN_INVALID)

    # 헤더의 access 토큰은 @jwt_required()가 "블록리스트에 없음"을 이미 확인했으므로 바로 추가한다.
    db.session.add(TokenBlocklist(jti=access_payload["jti"]))

    # body로 받은 refresh 토큰은 이미 폐기된 토큰일 수 있다.
    #   예) /refresh로 이미 사용한 옛 refresh 토큰을 프론트가 실수로 보낸 경우
    # TokenBlocklist.jti는 unique 컬럼이라 같은 jti를 또 넣으면 IntegrityError → 500이 난다.
    # 그래서 블록리스트에 없을 때만 추가한다.
    refresh_jti = refresh_payload["jti"]
    if not db.session.query(TokenBlocklist.id).filter_by(jti=refresh_jti).scalar():
        db.session.add(TokenBlocklist(jti=refresh_jti))

    # access와 refresh 폐기를 한 번에 커밋한다. (하나만 저장되고 하나는 빠지는 일이 없도록 한 트랜잭션으로)
    db.session.commit()
