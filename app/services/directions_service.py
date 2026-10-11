from datetime import datetime, timedelta, timezone   # 프론트엔드에서 받은 출발 시각을 처리하고, 예상 도착 시각을 계산할 때 사용

import requests                 # 카카오 길찾기 API에 HTTP 요청을 보낼 때 사용
from flask import current_app   # Flask 앱에 등록된 설정값을 읽을 때 사용 .env에 저장한 카카오 REST API 키를 가져옴

from app.errors import BusinessException, ErrorCode # 행사가 존재하지 않거나 길찾기 API 호출에 실패했을 때, 프로젝트의 공통 예외 처리 규칙
from app.extensions import db                       # 데이터베이스에서 행사 정보를 조회하고
from app.models.tour_content import Event           # 해당 행사의 위도와 경도를 가져오는 데 사용

KST = timezone(timedelta(hours=9))

class DirectionsService:
    @staticmethod
    def get_directions(event_id, query):
        # DB에서 요청한 행사 조회
        event = db.session.get(Event, event_id)

        # 행사가 존재하지 않으면 404 오류 처리
        if event is None:
            raise BusinessException(ErrorCode.EVENT_NOT_FOUND)

        # 행사에 목적지 좌표가 있는지 확인
        if event.latitude is None or event.longitude is None:
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

        # 출발 좌표 확인
        origin_lat = query.get("origin_lat")
        origin_lng = query.get("origin_lng")

        if origin_lat is None or origin_lng is None:
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        # 이동 수단 확인 나중에 된다면 기본은 transit
        mode = query.get("mode", "car")

        # 나중에 if mode not in ("transit", "car", "walk")
        if mode != "car":
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        # 좌표 범위 확인
        try:
            origin_lat = float(origin_lat)
            origin_lng = float(origin_lng)
        except (TypeError, ValueError):
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        if not (-90 <= origin_lat <= 90):
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        if not (-180 <= origin_lng <= 180):
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        # 출발 시각 확인
        departure_time = query.get("departure_time")

        if not departure_time:
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        try:
            departure_time = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        # 시간대 정보가 없는 시각은 허용하지 않음
        if departure_time.tzinfo is None:
            raise BusinessException(ErrorCode.COMMON_INVALID_INPUT)

        # 출발 시각을 한국 시간으로 변환
        departure_time = departure_time.astimezone(KST)

        # 자동차 길찾기 API 주소
        url = "https://apis-navi.kakaomobility.com/v1/directions"

        # Flask 설정에서 REST API 키 가져오기
        api_key = current_app.config.get("KAKAO_CLIENT_ID")

        # API 키가 없으면 요청할 수 없음
        if not api_key:
            raise BusinessException(ErrorCode.DIRECTIONS_API_KEY_MISSING)

        # 카카오 API는 경도, 위도 순서로 좌표를 전달함
        params = {
            "origin": f"{origin_lng},{origin_lat}",
            "destination": (
                f"{float(event.longitude)},{float(event.latitude)}"
            ),
        }

        # 인증 정보 설정
        headers = {
            "Authorization": f"KakaoAK {api_key}"
        }

        # 자동차 경로 요청 및 오류 처리
        try:
            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=10,
            )

            # HTTP 4xx 또는 5xx 응답이면 예외 발생
            response.raise_for_status()

            # JSON 응답을 파이썬 딕셔너리로 변환
            result = response.json()

        except requests.Timeout:
            # 카카오 서버가 제한 시간 내에 응답하지 않음
            raise BusinessException(ErrorCode.DIRECTIONS_API_TIMEOUT)

        except requests.HTTPError:
            # 카카오 API가 HTTP 오류 상태 코드를 반환함
            raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

        except requests.RequestException:
            # 연결 실패 등 기타 요청 오류
            raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

        except ValueError:
            # JSON 형식이 올바르지 않음
            raise BusinessException(ErrorCode.DIRECTIONS_API_ERROR)

        # 경로 목록이 있는지 확인
        routes = result.get("routes")

        if not isinstance(routes, list) or not routes:
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

        # 첫 번째 경로의 요약 정보 확인
        summary = routes[0].get("summary")

        if not isinstance(summary, dict):
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

        duration = summary.get("duration")
        distance = summary.get("distance")

        # 소요 시간과 거리가 숫자인지 확인
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not isinstance(distance, (int, float))
            or isinstance(distance, bool)
            or duration < 0
            or distance < 0
        ):
            raise BusinessException(ErrorCode.ROUTE_NOT_FOUND)

        # 출발 시각에 이동 소요 시간을 더해 예상 도착 시각 계산
        arrival_time = departure_time + timedelta(seconds=duration)

        return {
            "event_id": event.id,
            "mode": "car",
            "duration_minutes": round(duration / 60),
            "distance_meters": distance,
            "arrival_time": arrival_time.isoformat(),
        }

