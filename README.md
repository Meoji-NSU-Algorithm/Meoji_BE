# CheonanOn_BE

## 1. 실행 방법

0. 파이썬 버전 맞추기 (팀원마다 로컬 파이썬 버전이 다를 수 있어요)
   ```
   파이썬 org 홈페이지에서 3.14.7 릴리스 자기 OS 환경에 맞추어 다운로드
   ```
1. 가상환경 생성 및 활성화
   ```
   git 으로 파일 받아온 후
   파이참 아래 인터프리터설정
   새 인터프리터 추가 로컬 인터프리터 추가 누르기
   새로 만들기 누르고 파이썬 3.14누르기
   이후 터미널에서 파이썬 버전 확인 3.14.7 나와야함
   python --version
   ```
2. 의존성 설치
   ```bash
   # 클론 후 의존성 받아올 때 (개발/테스트까지 하려면 requirements-dev.txt)
   pip install -r requirements.txt
   pip install -r requirements-dev.txt
   ```
   - 패키지를 새로 설치했다면 **운영에 필요한 것만** `requirements.txt`에 직접 추가합니다. 개발 가상환경에서 `pip freeze > requirements.txt`를 하면 pytest 같은 개발용 패키지까지 섞이므로 사용하지 않습니다. 테스트용 패키지는 `requirements-dev.txt`에 추가합니다.
   - `cryptography`는 코드에서 직접 import하지 않지만, MySQL 8 기본 인증 방식(`caching_sha2_password`)으로 PyMySQL이 접속할 때 필요합니다.
3. 앱 실행
   ```bash
   python wsgi.py
   ```
   - 디버그 모드(코드 수정 시 자동 재시작)는 기본으로 꺼져 있습니다. 로컬 개발에서는 `.env`에 `FLASK_DEBUG=1`을 추가하세요. 외부에서 접근 가능한 환경에서 디버그 모드를 켜면 위험하므로 배포 환경에서는 켜지 않습니다.
   - 축제 데이터 자동 수집 스케줄러는 `python wsgi.py`로 실행할 때만 시작됩니다. `flask run`이나 gunicorn으로 띄우면 시작되지 않습니다.
4. 접속 주소: `http://127.0.0.1:5000` (호스트/포트를 별도 지정하지 않아 Flask 기본값을 사용합니다.)

## 1-1. 프로젝트 구조

기능(도메인)별로 폴더를 나누고, 한 도메인의 라우트·서비스·모델·스키마를 같은 폴더에서 찾을 수 있습니다.

```
app/
├─ __init__.py        create_app() 앱 팩토리
├─ models.py          모든 도메인 모델을 import (Flask-Migrate가 모델을 인식하게 하는 용도)
├─ core/              도메인 공통 코드
│  ├─ config.py  extensions.py  response.py  jwt_callbacks.py
│  ├─ api.py          /api 부모 Blueprint, 도메인 Blueprint 등록
│  ├─ db.py  time.py  공용 TimestampMixin, KST 상수
│  └─ errors/         ErrorCode, BusinessException, 전역 에러 핸들러
└─ domains/
   ├─ auth/     routes  service  kakao_client  token_service  models  schemas
   ├─ users/    routes  service  models  schemas
   ├─ events/   routes  service  models  schemas
   ├─ reviews/  routes  service  models  schemas
   └─ tour/     client  sync_service  state_service  scheduler  models
tests/
├─ conftest.py   전용 MySQL 테스트 DB 생성/삭제
├─ unit/<도메인>/  도메인별 단위 테스트
└─ integration/    HTTP 흐름 통합 테스트
```

- 새 도메인은 `app/domains/<도메인>/`에 만들고 `app/core/api.py`에 Blueprint를 등록합니다. 도메인 폴더의 `__init__.py`는 비워 둡니다. 도메인끼리 서로 import할 때 순환 import가 생기는 것을 막기 위해서입니다.
- 새 모델을 만들면 `app/models.py`에도 import를 추가합니다.

## 1-2. 테스트 실행

```bash
pytest
```

- `.env`의 `SQLALCHEMY_DATABASE_URI`와 같은 MySQL 서버에 `<DB이름>_test_<프로세스ID>` 이름의 임시 DB를 만들어 사용하고, 테스트가 끝나면 삭제합니다. 개발 DB는 건드리지 않습니다. 접속 계정에 `CREATE DATABASE` 권한이 필요합니다.
- 외부 API(Kakao, TourAPI)는 호출하지 않고 mock으로 대체합니다.

## 1-3. API 변경 사항 (구조 리팩토링 이후)

- 행사 API 경로가 `/api/event/...`에서 `/api/events/...`로 바뀌었습니다.
- 행사 응답 JSON 키가 camelCase에서 snake_case로 바뀌었습니다. (예: `startDate` -> `start_date`, `totalCount` -> `total_count`)
- 행사 목록과 월간 TOP은 결과가 없어도 404 대신 `200`과 빈 목록을 반환합니다.
- `GET /api/reviews/event/<event_id>`와 `GET /api/reviews/event/<event_id>/rating`은 기존처럼 로그인이 필요하며, 존재하지 않는 행사는 200 빈 응답 대신 404를 반환합니다.
- 404/405 같은 HTTP 에러의 `code`가 `COMMON_NOT_FOUND`, `COMMON_METHOD_NOT_ALLOWED` 형식으로 통일되었습니다.

## 2. Git 브랜치 전략

- **`main`**: 항상 배포 가능한 안정 버전만 유지합니다. `develop`에서 통합 테스트를 통과한 뒤 팀장이 직접 merge합니다.
- **`develop`**: 팀원들의 작업이 모이는 통합 브랜치입니다. 모든 `feature/*` 브랜치는 여기서 분기하고, 여기로 merge됩니다.
- **`feature/도메인명-이름`** (예: `feature/auth-MinYeong`, `feature/posts-Chulsoo`): 각자 담당 도메인 작업용 브랜치입니다. `develop`에서 분기해서 생성합니다. 같은 도메인을 여러 명이 나눠 맡을 수 있으니 브랜치 이름 끝에 본인 이름을 붙입니다.

### 작업 순서

1. `develop` 브랜치에서 최신 상태로 pull
2. `git checkout -b feature/도메인명-이름` (`develop` 기준으로 분기)
3. 해당 도메인 작업 진행
4. 작업 완료 후 `git add`, `commit`, `push`
5. GitHub에서 `feature/도메인명` → `develop`으로 Pull Request 생성
6. 코드 리뷰 후 `develop`으로 merge
7. `develop`에서 통합 테스트 통과 확인되면, 팀장이 `develop` → `main`으로 merge (배포 시점)

### 주의사항

- `feature` 브랜치를 `main`에서 분기하지 않도록 주의합니다 (반드시 `develop`에서 분기).
- `main`으로의 병합은 팀장만 진행합니다.

## 3. 커밋 컨벤션

커밋 메시지는 `타입: 내용` 형식으로 작성합니다.

```
feat: 카카오 로그인 API 추가
fix: 토큰 만료 시간 계산 오류 수정
docs: README 실행 방법 보강
refactor: 에러 클래스 구조 정리
```

| 타입 | 의미 |
|---|---|
| `feat` | 새로운 기능 추가 |
| `fix` | 버그 수정 |
| `docs` | 문서 수정 (README, 주석 등) |
| `refactor` | 기능 변경 없는 코드 구조 개선 |
| `test` | 테스트 코드 추가/수정 |
| `chore` | 빌드/설정/의존성 등 기타 작업 |

- 제목은 한 줄로 간결하게, 마침표는 붙이지 않습니다.
- 여러 작업을 한 커밋에 몰아넣지 말고, 의미 단위로 쪼개서 커밋합니다.

## 4. DB 마이그레이션 (Flask-Migrate)

DB 스키마(테이블/컬럼) 변경은 `db.create_all()`처럼 자동으로 맞추지 않고, **Flask-Migrate(Alembic)**로 버전 관리합니다. 모델을 바꿀 때마다 변경 이력이 담긴 스크립트 파일을 만들어 git으로 공유하기 때문에, 팀원 전체가 같은 명령으로 로컬 DB를 동일한 스키마 상태로 맞출 수 있습니다.

### 최초 1회 설정

Flask CLI가 앱을 찾을 수 있도록 터미널에서 환경변수를 지정합니다 (`wsgi.py`에 `app = create_app()`이 있어 자동 인식됩니다).

```bash
export FLASK_APP=wsgi.py
```

### 새로 clone 했거나 pull 받은 뒤 (테이블 생성/갱신)

```bash
flask db upgrade
```

`migrations/versions/` 안의 스크립트들을 순서대로 적용해서 로컬 MySQL DB를 최신 스키마로 맞춰줍니다. 모델을 직접 만들거나 수정할 필요 없이 이 명령 한 줄이면 됩니다.

### 모델을 새로 추가하거나 수정했을 때

```bash
# 1. 모델 변경 후, 변경사항을 비교해서 마이그레이션 스크립트 생성
flask db migrate -m "feat: user 테이블에 nickname 컬럼 추가"

# 2. migrations/versions/ 에 생성된 스크립트를 열어서 의도한 대로 만들어졌는지 확인
#    (자동 생성이 완벽하지 않을 수 있어 리뷰 필수)

# 3. 실제 DB에 반영
flask db upgrade
```

- `-m` 뒤의 마이그레이션 메시지도 **커밋 컨벤션과 동일한 타입 접두어**(`feat`, `fix`, `refactor` 등)를 붙여서 작성합니다. 나중에 `migrations/versions/`만 훑어봐도 어떤 변경이 어떤 의도였는지 알 수 있게 하기 위함입니다.
- 모델 파일과 그 모델로 생성된 마이그레이션 스크립트(`migrations/versions/*.py`)는 **같은 커밋에 함께 포함**합니다. 스크립트 없이 모델만 커밋하면 다른 팀원은 `flask db upgrade`를 해도 테이블이 생기지 않습니다.
- `migrations/` 폴더 전체(`alembic.ini`, `env.py`, `script.py.mako`, `versions/`)는 git으로 관리되는 프로젝트 파일입니다. `.gitignore`에 추가하지 마세요.

