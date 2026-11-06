---
name: 버그 리포트
about: 머지된 코드에서 발견된 버그·테스트 실패
title: "[BUG] "
labels: bug
assignees: ""
---

## 대상
- 관련 PR: #
- 담당자:
- 심각도: High / Med / Low

## 위치
`파일경로:라인`

## 현상
<!-- 실제로 어떻게 동작하는지 -->

## 기대 동작
<!-- FE 요구(backend-requests.md 절 번호) 또는 팀 규칙 기준 -->

## 재현 방법 / 실패 테스트
```
pytest tests/... -q
```

## 수정 가이드
<!-- 권장 수정 방향. 대안이 있으면 함께 적고, FE와 합의가 필요하면 표시 -->

## 완료 조건
- [ ] 수정 후 관련 테스트 통과
- [ ] 회귀 테스트 추가
- [ ] `pytest tests/unit tests/integration` 전체 통과
