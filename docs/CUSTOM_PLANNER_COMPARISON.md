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
`simulation_status=not_run`으로 남는다. 예외 또는 잘못된 반환형은 batch를 중단하고,
완료되지 않은 manifest/부분 CSV를 남긴다. 리포트는 완료된 batch만 읽는다.

선택적인 `config`는 manifest에 저장한다. JSON 호환 mapping과 dataclass는 중첩된
값까지 보존하며 tuple은 JSON 배열로 기록한다. 문자열 key, 문자열·bool·정수·유한
실수·null, list/tuple, mapping과 dataclass 조합을 지원한다. `Path`, `ndarray` 등
미지원 객체는 플래너 이름과 설정 위치가 포함된 CLI 오류로 결과 디렉터리·파일 생성 전에
거부한다. 경로는 문자열, 배열은 list로 명시적으로 바꿔 제공한다. 누락된 config는 `{}`이다.

## 비교와 산출물의 의미

- 각 플래너는 한 번 계획하고 그 경로를 모든 주행 seed에서 재사용한다. 계획시간을
  seed 수만큼 독립 반복한 것으로 해석하지 않는다. 확률적 플래너의 별도 seed API는 없다.
- `planning_time_ms`는 플래너가 반환한 `planning_time_s`를 ms로 바꾼 자체 보고값이다.
  실행기가 wall time을 측정하지 않으므로 미계측 사용자 플래너의 기본값 0은 실제
  계산시간 0을 뜻하지 않는다. PNG에도 planner-reported로 표시한다.
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
