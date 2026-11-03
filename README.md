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

Python 3.11 이상에서 저장소 루트에서 실행합니다.

```powershell
python -m pip install -e ".[dev]"
python -m raceplan.workflow scenarios/demo.yaml --simulation-seeds 0 1 2 --output-dir results/raw/comparison
```

한 명령으로 비교 실행 → 저장 결과 분석 → PNG 생성까지 진행합니다. 설치 후에는
`raceplan-workflow`도 같은 인자를 받습니다. 기존 폴더는 덮어쓰지 않으므로 새 실행에는
새 `--output-dir`을 지정합니다. 폴더에 `comparison.csv`, 경로·궤적 CSV와 manifest,
`analysis/`, `comparison.png`, 단계별 상태를 기록한 `workflow.json`이 생깁니다.

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
python -m raceplan.analyze results/raw/comparison/comparison.csv --baseline astar --output-dir results/analysis/reanalysis
python -m raceplan.custom_report results/raw/comparison/comparison.csv --seed 1 --output results/figures/selected_seed.png
```

`uv`를 사용하는 환경은 `uv sync --python 3.13 --extra dev` 후 각 명령을
`uv run --python 3.13 python -m ...`으로 실행할 수 있습니다.

## 사용자 플래너

[examples/my_planner.py](examples/my_planner.py)를 복사해 `Planner`의
`name`과 `plan(grid, start, goal, *, timeout_s=None)`을 구현합니다.
예제는 연결 확인용 A* 위임 코드입니다. 반환값은 `PlannerResult`이며,
성공 경로는 월드 좌표 미터와 radian을 사용하는 `Pose2D` 목록입니다.

```powershell
python -m raceplan.workflow scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output-dir results/raw/custom
```

`--planners astar hybrid_astar`로 baseline을 선택하고 `--custom-planner`를
반복해 여러 사용자 플래너를 추가할 수 있습니다. 이름은 서로 달라야 합니다.
사용자 파일은 Python 코드로 실행되므로 신뢰할 수 있는 파일을 지정합니다.
인터페이스·설정·실패 처리는 [사용자 플래너 안내](docs/CUSTOM_PLANNER_COMPARISON.md)를 참고하세요.

## 비교 조건과 해석

모든 플래너와 주행은 같은 `--inflation-radius` 지도를 사용하며 기본값은 0m입니다.
Dijkstra/A*는 점의 격자 연결성, Hybrid A*는 회전한 차량 footprint를 검사합니다.
탐색의 충돌 제약은 서로 다르며 실제 주행 충돌은 공통 시뮬레이터로 평가합니다.

계획은 플래너당 한 번 실행해 여러 주행 seed에 재사용합니다. 계획시간은 플래너의
자체 보고값이고 seed별 독립 측정이 아닙니다. `path_cost_m`은 기존 컬럼명이며
플래너별 비용 정의가 다를 수 있습니다. 실제 경로 길이는 분석에서 별도로 계산합니다.
사용자 플래너의 timeout은 구현이 협조해야 적용됩니다.

시나리오 YAML의 지도 경로는 시나리오 파일 기준입니다. `map_seed`는 지도 생성
출처 기록, `simulation_seed`는 주행 잡음에 사용합니다. 지도 형식은
[maps/README.md](maps/README.md)를 참고하세요.

## 개발과 연구 자료

테스트는 설치 후 `python -m pytest -q`로 실행합니다. 마지막 전체 검증은 97 passed입니다.

효과가 확인되지 않은 후보와 버전별 실험은 기본 사용 안내에서 제외했습니다.
연구 기능의 상태·보존 이유·이전 문서 위치는 [기능 범위](docs/FEATURE_SCOPE.md),
저장된 실험 결과는 [결과 폴더](results/README.md),
최신 작업 상태는 [HANDOFF](docs/HANDOFF.md)를 참고하세요.

