# 결과 폴더

기본 실행은 `python -m raceplan.experiment`, 분석은 `python -m raceplan.analyze`,
이미지는 `python -m raceplan.custom_report`를 사용한다.
실행 예시는 [프로젝트 README](../README.md)를 참고한다.

| 위치·파일 | 내용 |
|---|---|
| raw/<이름>.csv | episode 요약 |
| raw/<이름>_paths.csv | 계획 경로 |
| raw/<이름>_trajectory.csv | 전체 주행 궤적 |
| raw/<이름>_manifest.json | 설정·입력·소스 hash·완료 상태 |
| analysis/<이름>/ | episodes / planners / paired / clearance 및 분석 provenance |
| figures/<이름>.png | 저장 경로·궤적과 전체 seed 결과 |

summary와 companion 파일은 함께 유지한다. 기존 출력 이름은 재사용하지 않는다.
raw와 packages 및 상세 시계열은 Git 제외 로컬 자료여서 별도 백업이 필요하다.

## 보관된 연구 결과

| 묶음 | 상태 |
|---|---|
| custom_planner_20261103_reviewed | 사용자 플래너 연결 검증 |
| turn_aware_20261103 | 방향 비용 후보 데모 개발 비교 |
| turn_aware_holdout_20261103 | 신규 split 120건. 후보 일반 개선 근거 부족 |
| turn_aware_holdout_20261103_correction_v2 | query 숫자형 identity 사후 정정 |
| recovery_* | 회복 버전별 비교. 기본 CLI와 별도 |
| obstacle_guard_20261013 | 충돌 감소와 도달 악화 기록 |
| corridor_width_* / research_* | 과거 통로·비용 후보 연구 |

날짜별 Python 스크립트는 연구 재현용으로 보존한다. 위치와 내용을 바꾸면 저장된
source hash 검증에 영향을 주므로 그대로 유지한다. 이미 노출된 evaluation은
새 후보의 미사용 평가로 재사용하지 않는다.

과거 결과 안내 전문은 [보관 문서](../docs/archive/results_README.before_cleanup_20261104.md),
기능 상태는 [기능 범위](../docs/FEATURE_SCOPE.md)를 참고한다.
