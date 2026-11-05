# 기능 범위 정리 — 2026-11-04

기본 사용 흐름은 비교 실행 → 저장 결과 분석 → PNG 생성이다.
이번 정리는 사용자 진입점과 개발 우선순위를 정돈한다.

| 구분 | 기능 | 처리 |
|---|---|---|
| 핵심 | Dijkstra / A* / Hybrid A* | 기본 비교 대상으로 유지 |
| 핵심 | 사용자 Planner 로더·같은 seed 비교 | 유지 |
| 핵심 | 공통 차량·제어·충돌·잡음 | 유지 |
| 핵심 | CSV·manifest·분석·PNG | 기본 안내의 단일 흐름으로 통합 |
| 연구 보관 | Clearance A* | 성공률 개선 없음. 기본 기능·개발 우선순위에서 제외 |
| 연구 보관 | 방향-state A*·가중치 0·급회전 제곱 비용 | 기존 후보는 validation 회귀·evaluation 일부 성공. 제곱 비용 후속 후보도 validation 도달률 회귀로 중단. 기본 플래너 채택 보류 |
| 연구 보관 | guard·회복 v1~v4·접근 감속 | Python API와 과거 실험에 유지. 기본 CLI는 비활성 |
| 호환 도구 | compare / plot_comparison | 계획만 보는 기존 명령 유지. 기본 안내는 저장 결과 기반으로 통일 |
| 연구 보관 | 날짜별 suite·runner·봉인 교정 | 재현·감사 목적으로 원래 경로 유지 |

## 정리한 내용

README 두 언어판에서 중복 설명·과거 테스트 수·오래된 다음 작업·실험별 실행 명령을
걷어냈다. 이전 내용은 archive에 보존했다. results 안내도 현재 핵심 출력과 과거
실험 목록을 구분한다. 새로운 후보 구현·평가의 자동 연속 진행은 현재 우선순위에서
제외하며 다음 개발은 사용자가 필요한 기능과 실제 사용자 플래너를 기준으로 정한다.

## 연구 코드의 보존 이유

실행 소스와 경로가 기존 protocol/seal의 hash 검증 대상이다. 파일 이동·삭제나
코드 축소는 봉인된 결과의 재현 확인을 깨뜨릴 수 있다. 현재 정리에서는 실행 코드를
변경하지 않고, 검증된 기본 동작과 연구 기록을 유지했다.

이전에 생성한 raw 데이터·PPTX·중간 결과는 사용자 자료로 유지했다.
기능을 물리적으로 삭제하는 후속 작업에는 재현 자료를 포함한 별도 보관 방식이 필요하다.

## 연구 기록

- [사용자 플래너 인터페이스](CUSTOM_PLANNER_COMPARISON.md)
- [방향-state 후보](TURN_AWARE_CANDIDATE.md)
- [신규 split 평가와 query identity 정정](TURN_AWARE_HOLDOUT.md)
- [급회전 제곱 비용 개발 비교](SHARP_TURN_DEVELOPMENT_20261105.md)
- [회복 정책과 과거 결과](RECOVERY_20261013.md)
- [이전 한국어 README](archive/README.before_cleanup_20261104.md)
- [이전 영어 README](archive/README.en.before_cleanup_20261104.md)
