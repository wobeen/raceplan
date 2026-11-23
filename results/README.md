# 결과 폴더

`raceplan-workflow`는 한 시나리오의 비교·분석·PNG를, `raceplan-suite`는 여러
시나리오의 개별 결과와 집계를 저장한다. `raceplan-report`는 저장된 결과에서 공유용
HTML과 대표 PNG를 만든다. 실행 예시는 [프로젝트 README](../README.md)를 참고한다.

| 위치·파일 | 내용 |
|---|---|
| `raw/<실행>/` | workflow/suite 상태, episode·경로·전체 궤적 CSV, manifest, 분석, PNG. 예전 실행은 `raw/` 바로 아래에도 보관 |
| `reports/<리포트>/` | 공유할 `index.html`, `images/`, `provenance.json` |
| `analysis/`, `figures/` | Git에 선별해 기록한 연구 요약·그림. 상세 시계열과 일부 중간 결과는 Git 제외 |
| `packages/` | 별도로 만든 재현용 보관본. Git 제외 |

## 공유와 백업

공유할 때는 HTML 리포트 폴더 전체를 복사한다. `index.html`을 열면 로컬 PNG와
provenance가 상대경로로 연결된다. provenance에는 생성 당시 입력과 소스의 경로·hash가
포함된다. 저장 결과에서 리포트를 다시 생성하려면 원본 요약·경로·궤적·분석과 manifest가
참조하는 지도 YAML·이미지가 필요하다.

`raw/`, `reports/`, `packages/`, 일부 상세 시계열·중간 결과는 로컬 산출물이며 Git에서
제외한다. Git에는 코드·입력 예제·문서와 선별한 연구 요약을 기록한다. 실험을 보존하려면
summary와 companion 파일, 상태·manifest·분석, 사용한 설정·지도·시나리오·custom 소스,
Git 커밋과 `uv.lock`을 함께 백업한다. 외부 입력과 로컬 소스 수정본도 백업에 포함하고,
manifest의 경로와 hash로 원본 일치를 확인한다. 실행이나 리포트 생성마다 새 출력 폴더를 쓴다.

봉인한 실행은 `protocol.json`, `seal.json`, 실행 전 설계와 당시 소스·입력, 원시 결과 및
검증 기록을 함께 보존한다. 원본은 읽기 전용으로 취급하고 정정은 별도 파일에 남긴다.
재현에는 당시 소스·입력과 기록된 실행 환경을 사용하며 이미 실행한 봉인 폴더는 재사용하지
않는다. [holdout 봉인·정정 기록](../docs/TURN_AWARE_HOLDOUT.md)을 참고한다.

## 보관된 연구 결과

| 묶음 | 상태 |
|---|---|
| custom_planner_20261103_reviewed | 사용자 플래너 연결 검증 |
| turn_aware_20261103 | 방향 비용 후보 데모 개발 비교 |
| turn_aware_holdout_20261103 | 신규 split 120건. 후보 일반 개선 근거 부족 |
| turn_aware_holdout_20261103_correction_v2 | query 숫자형 identity 사후 정정 |
| sharp_turn_development_20261105 | 공개 validation 60건. 급회전 제곱 비용도 도달률 회귀로 중단 |
| smoothing_development_20261123 | 공개 validation 48건. A* 후처리 목표0.30 개발 선택, held-out 미실행 |
| recovery_* | 회복 버전별 비교. 기본 CLI와 별도 |
| obstacle_guard_20261013 | 충돌 감소와 도달 악화 기록 |
| corridor_width_* / research_* | 과거 통로·비용 후보 연구 |

날짜별 Python 스크립트는 연구 재현용으로 보존한다. 위치와 내용을 바꾸면 저장된
source hash 검증에 영향을 주므로 그대로 유지한다. 이미 노출된 evaluation은
새 후보의 미사용 평가로 재사용하지 않는다.

과거 결과 안내 전문은 [보관 문서](../docs/archive/results_README.before_cleanup_20261104.md),
기능 상태는 [기능 범위](../docs/FEATURE_SCOPE.md)를 참고한다.
