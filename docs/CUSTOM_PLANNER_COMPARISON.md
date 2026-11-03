# 사용자 플래너 비교 — 2026-11-03

## 구현 범위

`raceplan.experiment`의 `--custom-planner FILE.py:CLASS`로 사용자 플래너를 추가한다.
기본 Dijkstra/A*/Hybrid A* 또는 `--planners`로 선택한 baseline과 동일한 지도,
시작·목표, 계획 timeout, 차량, tracker, simulation seed와 잡음을 사용한다.
기본 guard/recovery 설정을 변경하지 않으며 이 CLI는 개발용 기본 주행 조건이다.

프로젝트가 설치된 환경(`uv sync --python 3.13 --extra dev` 등)에서 아래 명령을 사용한다.
현재 로컬 `.venv`처럼 프로젝트가 미설치된 환경에서는 PowerShell 세션에
`$env:PYTHONPATH = (Resolve-Path src).Path`를 먼저 설정해 소스에서 실행할 수 있다.

```powershell
.venv/Scripts/python.exe -m raceplan.experiment scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output results/raw/my_comparison.csv
.venv/Scripts/python.exe -m raceplan.custom_report results/raw/my_comparison.csv --output results/figures/my_comparison.png
.venv/Scripts/python.exe -m raceplan.analyze results/raw/my_comparison.csv --baseline astar --output-dir results/analysis/my_comparison
```

예제 `MyPlanner`는 A*에 위임한다. 비교 연결 예제이며 개선 알고리즘을 뜻하지 않는다.
여러 사용자 플래너를 비교하려면 `--custom-planner`를 반복한다. 각 클래스는
인자 없이 생성 가능해야 하며 `raceplan.planners.base.Planner`를 상속한다.
`name`은 앞뒤 공백·콜론·제어문자 없는 고유 문자열이고 다음 인터페이스를 구현한다.

```python
def plan(self, grid, start, goal, *, timeout_s=None) -> PlannerResult:
    ...
```

성공 시 `PlannerResult(PlannerStatus.SUCCESS, Path(...))`에 월드 좌표 미터와
radian의 `Pose2D`를 넣는다. 실패 시 `NO_PATH`, `INVALID_START`, `INVALID_GOAL`,
`TIMEOUT` 중 상태를 반환하고 path는 넣지 않는다. 정상적인 계획 실패는 모든 seed에
`simulation_status=not_run`으로 남는다. 2026-11-04 experiment revision2부터 사용자
`plan`의 일반 예외 또는 데이터 계약을 어기는 반환값은 `planning_error`로 전환하고
나머지 planner 비교를 계속한다. 모든 seed에 `planning_error_type/message`, 실측 시간과
`not_run`을 기록하며 유효하지 않은 경로·미검증 reported time/expanded nodes는 저장하지 않는다.
리포트는 완료된 batch만 읽는다. 전체 planner가 실패해도 완료된 batch는 분석·PNG를 만든다.

계약 검사는 PlannerResult/PlannerStatus, 성공 시 비어 있지 않은 Pose2D sequence,
유한 좌표·비용·reported time, 비음수 비용·시간·정수 탐색량, 실패 시 path 없음 등이다.
reported seconds를 milliseconds로 변환한 값까지 유한해야 한다.
유효한 list/tuple 경로는 tuple snapshot으로 복사한다. 충돌 안전성·최적성·추종 가능성이나
목표 도달을 데이터 계약 검사에서 추가 판정하지 않는다. `planning_error`는 일반적인
`no_path`/`timeout`과 구분되고 분석에서 전체 planning_failures에도 포함된다.

import/생성/config 오류와 builtin 내부 예외·계약 오류는 batch를 중단하며 부분 CSV와
미완료 manifest를 보존한다. `KeyboardInterrupt`·`SystemExit`는 plan adapter 밖으로
전파하고 이후 planner를 실행하지 않는다. workflow는 이 중단을 failed phase로 기록한다.
custom 오류 뒤에도 처리된 batch의 workflow complete는 모든 planner 성공을 뜻하지 않는다.

선택적인 `config`는 manifest에 저장한다. JSON 호환 mapping과 dataclass는 중첩된
값까지 보존하며 tuple은 JSON 배열로 기록한다. 문자열 key, 문자열·bool·정수·유한
실수·null, list/tuple, mapping과 dataclass 조합을 지원한다. `Path`, `ndarray` 등
미지원 객체는 플래너 이름과 설정 위치가 포함된 CLI 오류로 결과 디렉터리·파일 생성 전에
거부한다. 경로는 문자열, 배열은 list로 명시적으로 바꿔 제공한다. 누락된 config는 `{}`이다.

## 비교와 산출물의 의미

- 각 플래너는 한 번 계획하고 그 경로를 모든 주행 seed에서 재사용한다. 계획시간을
  seed 수만큼 독립 반복한 것으로 해석하지 않는다. 확률적 플래너의 별도 seed API는 없다.
- `planning_time_ms`는 플래너가 반환한 `planning_time_s`를 ms로 바꾼 자체 보고값이다.
  미계측 사용자 플래너의 기본값0은 실제 계산시간0을 뜻하지 않는다. 유효한 결과를
  얻지 못한 custom 오류의 reported time과 expanded nodes는 비어 있다.
- `runner_planning_time_ms`는 실행기의 perf_counter로 plan 호출1회만 실측한 값이다.
  호출의 예외 unwind를 포함하며 로딩/지도 사본/반환 데이터 검증/주행은 제외한다.
  모든 seed에 같은 측정값을 기록하고 분석 집계는 saved plan1회로 세어 중복 표본을 만들지 않는다.
  PNG는 reported와 runner wall을 따로 표시한다. 구 batch에 없는 실측값은 n/a/null이다.
- 플래너별 지도 사본을 제공하므로 사용자 코드가 배열 쓰기를 켜서 수정해도 다른
  플래너와 시뮬레이터의 지도에 영향을 주지 않는다. 실행 시간 제한은 cooperative
  `timeout_s`이며 외부 프로세스에 의한 강제 중단은 제공하지 않는다.
- manifest에 사용자 파일 절대 경로·SHA-256·클래스명, 설정, RacePlan 소스 hash와
  실행 환경을 기록한다. 로더는 hash를 계산한 동일 소스 바이트를 실행한다.
  사용자 플래너의 외부 의존 파일·패키지까지 자동 보관하지 않는다.
- 사용자 코드는 현재 Python 프로세스에서 실행되므로 신뢰할 수 있는 파일만 사용한다.
- 요약 CSV의 `path_cost_m`은 기존 호환 컬럼명이다. 값의 단위는 각 planner 정의에
  따르며 실제 기하 경로 길이와 다를 수 있다. PNG는 planner cost와 XY 길이를 구분한다.
- PNG의 집계는 전체 seed의 도달·충돌·timeout·계획 실패를 포함한다. 궤적은 첫 seed를
  표시하며 `--seed N`으로 바꿀 수 있다. 경로/궤적 index를 정렬·확인하고 저장된 query와
  hash가 일치하는 물리 지도를 사용한다. 팽창 지도 사용 여부는 manifest에 기록된다.
- CSV·manifest·PNG는 기존 출력 파일을 덮어쓰지 않는다. 실패 중간 결과도 삭제하지 않는다.
- 상세 비교는 기존 `raceplan.analyze`를 사용한다. 같은 seed의 양쪽이 도달한 경우에만
  tracking RMSE·완료시간·조향 포화율 delta를 계산하며 모든 실패 수는 별도로 집계한다.
  최소 driving clearance delta는 충돌·timeout을 포함해 양쪽 모두 주행한 경우 계산한다.

성공 기준은 충돌 없이 목표 위치 0.5m 이내 진입이며 yaw는 참고값이다. 이 데모는
연결·저장·리포트 확인을 위한 개발 실행이고 held-out 일반화나 실차 성능의 근거가 아니다.

## 저장 형식과 과거 결과 호환

manifest의 schema_version1은 유지하고 `experiment_revision=2`로 이번 추가 필드와
오류 정책을 구분한다. CSV에 runner timing과 오류 type/message/truncated를 추가하며 구 batch는
새 컬럼 없이도 분석/PNG를 읽는다. 분석의 `planning_errors`는 `planning_failures`의
부분집합이다. 실패 baseline과의 paired 결과도 행을 남기고 양쪽 도달/주행 조건을
충족하지 못한 연속 지표는 비워 둔다. PNG의 오류 message는 공간상 잘릴 수 있지만
원본 CSV는 아래 저장 길이 제한 내의 문자열을 보존한다. 짧은 진단의 개행 원문은
CSV에 그대로 남기고 PNG에서만 개행/제어문자를 한 줄로 정규화한다.

오류 type은128자, message는4096자로 제한하며 자르면 `... [truncated]` 접미사와
`planning_error_truncated=True`를 기록한다. 전체 길이/자세한 원문은 자동 보관하지 않는다.
새 진단 필드가 CSV 기본 field limit을 넘지 않도록 하며, PNG 폭 맞춤은 문자별 재측정
대신 이진 탐색을 사용한다. 표시가 잘린 PNG와 저장 길이 제한은 별도 동작이다.

2026-11-04 스텝2는 현재 실행 소스의 후속 버전이다. 기존 sealed runner/raw/protocol과
source hash 기록은 바꾸지 않는다. 당시 src hash가 현재 src와 다른 것은 정상이며,
과거 sealed 실행의 live-source 검증/재개는 현재 코드로 거부될 수 있다. 과거 결과의
재현은 당시 커밋 소스나 저장 패키지를 사용한다. 저장 결과를 읽는 분석·PNG는 새 코드로
가능하지만 원본 파일을 덮어쓰지 않고 새 출력 이름을 사용한다.

## 스텝2 실행 확인

반환 계약/예외 경계, fake clock의 plan-only 실측, 오류 뒤 정상 planner 계속 실행,
모든 planning 실패 및 구 batch의 missing timing 처리를 구현 후 한 묶음으로 검증한다.
`examples/error_planners.py`는 일반 예외와 잘못된 반환값을 의도적으로 발생시키는
개발 확인용 클래스다. 정상 `MyPlanner`와 함께 workflow smoke에 사용하며 성능 후보가 아니다.
검증 결과와 Astra 독립 검토는 완료 후 기록한다.

구현 중 테스트0회, 구현 완료 뒤 관련pytest1회 **23 passed (6.16s)**, 전체1회
**103 passed (9.98s)**, 정상/예외/잘못된 반환 custom을 포함한 workflow smoke1회를
묶어서 실행했다. smoke는6planner×3seed18행으로 정상12행 모두 도달, 의도한
planning_error6행은not_run, 충돌/timeout/통상 계획실패0이다. 각 planner는1번 호출했고
그 실측을3seed에 재사용했다. 오류 뒤 MyPlanner도3건 도달하고 A*와 paired 주행
delta0을 유지했다. workflow/analysis/report 모두 complete이며 seed1 PNG 시각 확인 완료.

출력은 `results/raw/workflow_step2_20261104/`에 보존했다. 새 회귀는 계약 오류·
control exception/builtin propagation, 정상 경로 snapshot, plan-only fake-clock 실측,
오류 뒤 계속 실행·전체 실패·구 컬럼 호환을 확인했다. Astra 독립 검토는 다음 단계다.

Astra P2/P3 지적 후 진단 저장 길이/표시 및 milliseconds finite 검증을 보완했다.
수정 구현 완료 뒤 관련pytest1회 **24 passed (4.89s)**, 전체1회 **104 passed (7.14s)**를
묶어서 실행했다. 새 E2E는 개행/NUL message 보존·한 줄 PNG,14만자 type/message의
저장 제한과 truncation, ms overflow 거부, 이후 정상 planner 계속 실행과 분석/PNG 완료를
확인했다. 폭 맞춤의 측정 호출수도 제한해 문자별 반복 측정 회귀를 막았다. 이전18행
smoke는 보존했고 별도 smoke 재실행 없이 최종 소스를 E2E로 검증했다.
최종 승인 기록과 커밋은 주 에이전트가 진행한다.

## 이어서 진행할 개발 계획

1. 사용자 플래너 비교 연결, 소스 provenance, 모든 실패 저장 및 PNG를 이번 묶음에서 완료한다.
2. 비교할 실제 사용자 알고리즘과 고정 설정을 준비하면, 검증 지도에서 기존 분석기의
   paired 지표·경로 기하·clearance를 사용해 실패 조건과 계산비용을 확인한다.
   비위임 방향-state A*와 가중치0 예제 및 사전 고정한 demo 개발 비교는
   [TURN_AWARE_CANDIDATE.md](TURN_AWARE_CANDIDATE.md)에 정의했다.
3. 회복 v4는 기존 결과와 기본 v2를 보존한다. 비용 개선과 도달 개선을 구분하고,
   별도 후속 묶음에서 request 예산 소진 시나리오 및 남은 실패를 분석한다.
4. 신규 정책의 최종 성능 비교 전에는 새로운 held-out split과 예산을 고정한다.
   현재 validation 결과를 재튜닝해서 최종 평가로 보고하지 않는다.

이번 범위에서는 회복 정책 변경·재튜닝 또는 기존 frozen 실험 재실행을 포함하지 않는다.

## 구현 후 일괄 검증 기록

6.1-sol 구현이 끝난 뒤 전체 pytest를 한 번 실행해 **79 passed (4.72s)**를 확인했다.
사용자 플래너 회귀 테스트는 동일 seed 잡음의 전체 궤적 일치, 입력 지도 변경의 격리,
계획 실패 보존, 중복 이름 거부, 소스 변경 시 새 코드/hash 로딩, import 오류,
완료 batch 리포트와 덮어쓰기·없는 seed·지도 hash 불일치 거부를 포함한다.

첫 standalone 실행은 `.venv`의 프로젝트 미설치로 모듈 탐색 단계에서 종료했으며
산출물을 만들지 않았다. 해당 세션의 `PYTHONPATH=src` 설정 후 smoke 비교·PNG·상세
분석을 이어 실행했다. smoke는 무잡음 demo의 기본 3 planner+MyPlanner × seed 0/1/2,
총 **12건 모두 도달, 충돌0·timeout0·계획실패0**이다. 무잡음 seed 반복이므로 독립
성능 표본으로 해석하지 않는다. A* 위임 예제와 A*의 모든 paired 지표 delta는 0이다.

산출물은 `results/raw/custom_planner_20261103{,_trajectory,_paths}.csv`,
`results/raw/custom_planner_20261103_manifest.json`,
`results/figures/custom_planner_20261103.png`,
`results/analysis/custom_planner_20261103/`이다. PNG 시각 확인 완료.
raw와 clearance 세부 시계열은 ignore된 로컬 자료이므로 Git만으로 복원되지 않는다.
기존 출력과 사용자 PPTX 자료는 보존했으며 stage/commit하지 않았다.
Astra의 최종 독립 검증 결과는 아래 절에 기록한다.

### Astra 1차 지적 반영 후 최종 확인

설정 dict 유실 및 dataclass 내부 비-JSON 객체 때문에 빈 manifest가 생기는 P2를
수정했다. JSON 호환 mapping/dataclass를 보존하고 미지원 값·순환 참조·비유한 수·
비문자열 key는 위치를 포함해 명확히 거부한다. 전체 manifest 직렬화를 결과 생성
전에 수행한다. 일반 dict, dataclass+UserDict+tuple 보존과 내부 Path/ndarray의
무산출물 거부 회귀 검증을 추가했다. 계획시간 자체 보고 표기와 clearance delta
계산 대상 설명도 함께 반영했다.

수정 코드 완료 후 관련 테스트1회 **8 passed (1.33s)**, 전체 pytest1회
**80 passed (2.53s)**를 한 묶음으로 실행했다. 최종 소스로 새 smoke 비교12건을
실행해 모두 도달·충돌0·timeout0·계획실패0을 확인했고, PNG 생성/시각검토 및
기존 analyze 연계도 성공했다. MyPlanner의 A* 대비 모든 paired delta는 0이다.
최종 산출물은 이전 이름에 `_reviewed`가 붙는다:
`results/raw/custom_planner_20261103_reviewed*`,
`results/figures/custom_planner_20261103_reviewed.png`,
`results/analysis/custom_planner_20261103_reviewed/`. 이전 출력은 보존했다.

Astra는 최종 소스·지도·시나리오·분석 입력·예제 SHA-256 47개를 `_reviewed`
산출물과 직접 대조해 불일치0을 확인했다. 12/12가 목표거리0.5m 이내이고 충돌0이며,
A*와 MyPlanner의 저장 경로 및 각 seed의 258개 전체 궤적 sample이 일치한다.
PNG 구조/크기(1200×1605), 테스트 기록, P2 수정과 설명을 재검토했고 차단 사항 없이
최종 승인했다.
