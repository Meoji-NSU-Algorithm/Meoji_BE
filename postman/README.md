# 북마크 Postman 테스트

1. Postman에서 `bookmarks.postman_collection.json`을 import합니다.
2. Collection variables의 `baseUrl`을 실행 서버 주소로, `accessToken`을 테스트 계정의 유효한 access token으로 설정합니다.
3. `eventId`를 DB에 존재하는 테스트 행사 ID로 설정합니다. 기본값 `814`는 로컬/테스트 DB에 해당 행사가 있을 때만 사용할 수 있습니다.
4. `Bookmark lifecycle` 폴더를 순서대로 실행합니다.

컬렉션은 인증, 신규·중복 추가의 200 응답과 멱등성, 목록의 중복 여부와 `priceType`, 잘못된 입력, 토큰 누락, 해제 후 목록 반영을 확인합니다. 마지막 해제 요청이 테스트 계정의 해당 행사 북마크를 제거하므로, 테스트 전용 계정과 데이터를 사용하세요.
