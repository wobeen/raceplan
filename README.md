<p align="center"><strong>한국어</strong> | <a href="README.en.md">English</a></p>

# RacePlan

Dijkstra, A*, Hybrid A*와 직접 만든 플래너를 같은 지도·차량·제어 조건에서
비교하는 2D 주행 시뮬레이터입니다. 계획 경로와 실제 주행 결과를 함께 저장합니다.

## 기본 기능

- 기본 3종 및 사용자 플래너의 동일 seed 비교
- Pure Pursuit·PID·자전거 모델과 차량 직사각형 충돌 검사
- 도달·충돌·timeout·계획 실패, 추종 오차·경로 길이·clearance 분석
- 요약·경로·전체 궤적 CSV, 설정·소스 hash manifest, 결과 PNG

성공은 충돌 없이 후륜 축 중심이 목표 위치 0.5m 이내에 진입하는 것입니다.
최종 방향은 참고값입니다. 기본 실행의 장애물 감속·회복 옵션은 비활성입니다.

## 설치와 실행

Windows PowerShell에서 Python 3.11 이상을 사용합니다. 저장소 루트에서 새 가상환경을
만들고, 데모 한 건과 예제 suite를 실행한 뒤 저장된 suite로 HTML 리포트를 만듭니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[dev]"
.\.venv\Scripts\raceplan-workflow.exe scenarios/demo.yaml --simulation-seeds 0 1 2 --output-dir results/raw/comparison
.\.venv\Scripts\raceplan-suite.exe examples/suite.yaml --output-dir results/raw/my_suite
.\.venv\Scripts\raceplan-report.exe results/raw/my_suite --output-dir results/reports/my_suite
```

`uv`로 잠긴 의존성을 설치하려면 위 두 설치 명령 대신
`uv sync --locked --python 3.13 --extra dev --no-editable`을 실행합니다.
예제의 지도·시나리오·설정·사용자 플래너 파일은 저장소에서 읽습니다.

`raceplan-workflow`는 비교 실행, 저장 결과 분석, PNG 생성을 한 명령으로 처리합니다.
새 실행에는 새 `--output-dir`을 지정합니다. 폴더에 `comparison.csv`, 경로·궤적 CSV와
manifest, `analysis/`, `comparison.png`, 단계별 상태를 기록한 `workflow.json`이 생깁니다.

PNG의 집계는 전체 seed 기준이며 기본 첫 seed의 궤적을 표시합니다.
`--report-seed 1`로 표시할 궤적, `--baseline astar`로 분석 기준을 선택합니다.
기준을 생략하면 선택된 A*, A*가 없으면 첫 baseline을 사용합니다. `--spacing 0.1`은
분석 경로 샘플 간격(m)입니다. 잡음과 `--inflation-radius` 옵션도 기존 실행기와 같습니다.

입력·seed 오류는 가능한 실행 전에 거부합니다. 사용자 플래너를 두 번 import하지 않도록
사용자 baseline 이름은 실행 완료 manifest에서 확인합니다. 단계가 실패하면 후속 단계를
멈추고 `workflow.json`의 `failed_phase`와 부분 산출물을 보존합니다. 같은 폴더의 자동
재시도는 하지 않습니다. `--output` 같은 개별 모듈 출력 인자는 통합 명령에서 받지 않습니다.

저장 결과만 다시 분석하거나 PNG를 만들 때는 개별 명령을 사용합니다.

```powershell
.\.venv\Scripts\raceplan-analyze.exe results/raw/comparison/comparison.csv --baseline astar --output-dir results/analysis/reanalysis
.\.venv\Scripts\python.exe -m raceplan.custom_report results/raw/comparison/comparison.csv --seed 1 --output results/figures/selected_seed.png
```

`raceplan-report`는 저장된 단일 workflow 폴더도 받습니다. 생성한 `index.html`을 열고
리포트 폴더 전체를 공유할 수 있습니다. 실패·누락 coverage와 통계 분모, 대표 선정
규칙은 [저장 리포트 안내](docs/SAVED_REPORT.md)를 참고하세요.

## 저장 결과 탐색기

저장된 결과를 브라우저에서 직접 살펴봅니다. 인자가 없으면 `results/raw` 아래의 실행을
찾고(폴더가 없으면 빈 폴더를 만들어 시작), 폴더 하나를 지정해 바로 열 수도 있습니다. 저장된 결과를 볼 때는 계획이나 주행을
다시 실행하지 않으며 이 컴퓨터(127.0.0.1)에서만 접속됩니다. `Ctrl+C`로 종료합니다.

```powershell
.\.venv\Scripts\raceplan-gui.exe results/raw/my_suite
```

명령이 열거나 출력한 주소(`#token=…` 포함)로 열면 `+ 새 실행`으로 새 비교를 별도
프로세스에서 실행할 수 있습니다(시간 제한·취소, 결과는 `gui-runs/` 아래 새 폴더).
시나리오를 여러 개 고르거나 노이즈를 0보다 크게 주면 아래 "여러 시나리오 일괄 실행"과 같은
suite로 실행하고, 결과는 모든 case 합계 보기로 열립니다. 사용자 플래너 파일 경로를 넣고
"클래스 찾기"를 누르면 파일 안의 Planner 클래스를 체크박스로 고를 수 있습니다(파일을 읽기만
하고 실행하지 않음). watch를 켜면 파일을 저장할 때마다 같은 조건으로 다시 실행합니다.
`--no-run`은 실행 기능을 끕니다. 같은 일을 터미널에서 하려면:

```powershell
.\.venv\Scripts\raceplan-watch.exe examples/my_planner.py:MyPlanner --scenario scenarios/demo.yaml
.\.venv\Scripts\raceplan-watch.exe examples/my_planner.py:MyPlanner --scenario a.yaml --scenario b.yaml --seeds 11 12 13 --steering-std-rad 0.01
```

저장할 때마다 `results/raw/gui-runs/`에 새 결과를 만들고 planner별 도달 수를 출력합니다
(suite면 완료된 case 합계와 실패 case). 탐색기를 열어 두면 목록에 3초 안에 나타납니다. `--once`는
한 번만 실행하고 완료 여부를 종료 코드로 돌려줍니다. 노이즈 옵션은 `--help`에 있습니다. 플래너 파일의
코드는 이 컴퓨터에서 그대로 실행되니 신뢰하는 파일만 쓰세요.

목록의 각 실행에는 사용자 플래너 파일 버전(sha256 앞 8자리)과 watch 회차가 붙습니다. "실행 비교" 탭은 지금 연 실행을
고른 실행(기본: 같은 조건의 직전 실행)과 저장 결과로 비교합니다. 같은 시나리오·지도 파일이고 조건이 같은 case의 공통
seed만 짝짓고, planner별 도달 수 변화와 둘 다 도달한 쌍의 지표 차이(B − A)를 보여 줍니다.

Python 없이 쓰려면 Windows용 `RacePlan.exe` 배포판(zip)을 씁니다. 설치·실행·빌드는
[Windows exe 안내](docs/WINDOWS_EXE.md)를 참고하세요.

## 여러 시나리오 일괄 실행

YAML의 공통 설정으로 case별 workflow를 순차 실행하고 episodes/planning/paired 및
전체·시나리오별 집계 CSV를 만듭니다. 상대경로는 설정 파일 기준입니다. 실패 case는
부분 결과와 누락 coverage를 남기고 일반 오류 후 다음 case를 진행하며 최종 nonzero를
반환합니다. [설정·출력·중단 정책](docs/SUITE.md)을 참고하세요.

## 사용자 플래너

[examples/my_planner.py](examples/my_planner.py)를 복사해 `Planner`의
`name`과 `plan(grid, start, goal, *, timeout_s=None)`을 구현합니다.
예제는 연결 확인용 A* 위임 코드입니다. 반환값은 `PlannerResult`이며,
성공 경로는 월드 좌표 미터와 radian을 사용하는 `Pose2D` 목록입니다.

```powershell
.\.venv\Scripts\raceplan-workflow.exe scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output-dir results/raw/custom
```

`--planners astar hybrid_astar`로 baseline을 선택하고 `--custom-planner`를
반복해 여러 사용자 플래너를 추가할 수 있습니다. 이름은 서로 달라야 합니다.
사용자 파일은 Python 코드로 실행되므로 신뢰할 수 있는 파일을 지정합니다.
인터페이스·설정·실패 처리는 [사용자 플래너 안내](docs/CUSTOM_PLANNER_COMPARISON.md)를 참고하세요.
사용자 `plan`의 일반 예외나 잘못된 반환값은 모든 seed에 `planning_error`와 원인
유형·message를 기록하고 나머지 비교를 계속합니다. 긴 진단은 truncation 표시와 함께
저장 길이를 제한합니다. import/config 오류와 내부 baseline 버그는 실행을 중단하며
`KeyboardInterrupt`·`SystemExit`도 계획 실패로 바꾸지 않습니다.
`workflow.json`의 complete는 실행·분석·그림 처리 완료이며 모든 플래너의 도달을 뜻하지 않습니다.

## 비교 조건과 해석

모든 플래너와 주행은 같은 `--inflation-radius` 지도를 사용하며 기본값은 0m입니다.
Dijkstra/A*는 점의 격자 연결성, Hybrid A*는 회전한 차량 footprint를 검사합니다.
탐색의 충돌 제약은 서로 다르며 실제 주행 충돌은 공통 시뮬레이터로 평가합니다.

계획은 플래너당 한 번 실행해 여러 주행 seed에 재사용합니다. `planning_time_ms`는
플래너 자체 보고값, `runner_planning_time_ms`는 실행기가 plan 호출만 실측한 wall time입니다.
로딩·지도 복사·결과 검증·주행 시간은 실측 계획시간에 포함하지 않습니다. 두 시간 모두
같은 plan을 seed에 재사용한 값이며 seed별 독립 측정이 아닙니다. 구 batch의 실측값은 n/a입니다.
`path_cost_m`은 기존 컬럼명이며
플래너별 비용 정의가 다를 수 있습니다. 실제 경로 길이는 분석에서 별도로 계산합니다.
사용자 플래너의 timeout은 구현이 협조해야 적용됩니다.

시나리오 YAML의 지도 경로는 시나리오 파일 기준입니다. `map_seed`는 지도 생성
출처 기록, `simulation_seed`는 주행 잡음에 사용합니다. 지도 형식은
[maps/README.md](maps/README.md)를 참고하세요.

## 개발과 연구 자료

테스트는 설치 후 `.\.venv\Scripts\python.exe -m pytest -q`로 실행합니다.
마지막 전체 검증은 234개 테스트가 통과했습니다.

효과가 확인되지 않은 후보와 버전별 실험은 기본 사용 안내에서 제외했습니다.
A* 경로 후처리와 출발 lead-in 구제 같은 사용자 플래너 후보는 `examples/`에 연구용으로 두었습니다.
held-out 평가에서 승격 기준을 넘지 못해 기본 플래너가 아닙니다.
후보 개발·평가는 사전 등록 → 독립 검토 → 1회 실행 → 결과 커밋 순서를 따릅니다
([연구 절차](docs/COMMIT_PLAN.md), [승격 기준](docs/FEATURE_SCOPE.md)).
연구 기능의 상태·보존 이유·이전 문서 위치는 [기능 범위](docs/FEATURE_SCOPE.md),
저장된 실험 결과는 [결과 폴더](results/README.md),
최신 작업 상태와 다음 작업 후보는 [HANDOFF](docs/HANDOFF.md)를 참고하세요.

