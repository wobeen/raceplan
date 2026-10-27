# RacePlan

## 프로젝트 개요

RacePlan은 Dijkstra, A*, Hybrid A* 경로 계획 알고리즘을 동일한 물리적 지도와 차량 조건에서 비교하는 2D 주행 시뮬레이션 프로젝트입니다. 통로 폭, 장애물 배치, 회전 구간과 격자 해상도가 경로 계획과 실제 주행에 미치는 영향을 분석합니다.

경로가 생성되었더라도 차량의 크기와 조향 제약 때문에 주행 중 충돌하거나 정지할 수 있습니다. 따라서 **경로 계획 성공과 차량의 실제 목표 도달을 구분**하여 평가합니다. 목표 도달은 충돌 없이 후륜 축 중심이 목표 위치 0.5m 이내에 진입한 경우이며, 최종 방향은 요구하지 않습니다.

### 비교 대상과 주행 방식

- **Dijkstra와 A***: 격자 기반 경로 탐색. 차량 크기를 반영하기 위해 장애물을 확장한 계획 지도를 사용합니다.
- **Hybrid A***: 차량의 위치·방향과 조향 제약을 고려한 경로 탐색. 차량의 직사각형 형태를 충돌 검사에 반영합니다.
- 각 경로는 차량 조향과 이동을 표현하는 공통 시뮬레이터에서 주행합니다. 알고리즘별 장애물 처리 방식의 차이는 결과 해석에 포함합니다.

### 실험 조건

지도 특성의 영향을 구분하기 위해 기본 실험에서는 한 번에 하나의 특성을 변경하고 다른 조건을 유지합니다.

- **기본 환경**: 장애물이 없거나 주행 공간에 충분한 여유가 있는 지도에서 기본 성능을 확인합니다.
- **통로 폭**: 통로를 단계적으로 좁혀 경로 생성, 통과 및 충돌 여부를 비교합니다.
- **장애물 배치**: 단일·연속·좌우 교차 배치에서 우회와 반복 조향의 영향을 살펴봅니다.
- **회전 구간**: 완만한 회전과 급격한 방향 전환에서 조향 제약과 경로 추종 성능을 비교합니다.
- **격자 해상도**: 같은 물리적 환경을 서로 다른 격자 크기로 표현하여 지도 표현과 탐색 비용의 변화를 확인합니다.
- **출발·목표 조건**: 동일 지도에서 출발·목표 위치와 초기 방향을 바꾸어 결과의 변화를 확인합니다.

주행 제어는 기본 경로 추종, 장애물 감속·정지, 정지 후 재출발·재계획으로 구분해 비교합니다. 제어 조건 비교에는 같은 초기 경로를 사용하며, 재계획 후 경로가 달라지면 그 횟수와 추가 계산시간을 기록합니다. 지도별 본 비교에 사용할 제어 정책은 실험 전에 고정합니다.

차량 크기와 성능, 출발·목표, 제어 설정, 노이즈 설정과 seed를 비교 조건에 맞게 동일하게 유지합니다. 여러 seed로 반복하며, 탐색 노드 수와 시간 제한 및 실제 계산시간을 기록합니다. 구체적인 지도 조건의 수준과 반복 횟수는 추후 확정합니다.

### 평가 지표

- 목표 도달률, 충돌률, 계획 실패, 시간초과 및 회복 실패
- 경로 길이, 목표 도달시간 및 경로 계획 계산시간
- 장애물과의 최소 거리 및 경로 추종 오차
- 정지시간, 재출발·재계획 횟수 및 추가 계산시간

빠르게 종료된 실패를 성능 향상으로 오해하지 않도록 주행시간은 성공 사례끼리도 비교합니다. 주행 시뮬레이션 시간과 경로 계획에 사용한 실제 계산시간도 구분합니다.

### 기대 효과 및 향후 계획

지도 환경에 따른 알고리즘의 성능과 한계를 비교하고, 차량의 조향 제약과 주행 제어가 목표 도달에 미치는 영향을 파악합니다. 격자 해상도의 변화에 따른 경로 표현과 계산 비용의 관계도 살펴봅니다.

개발용 지도에서 실험 설정을 조정한 뒤, 설정을 고정하고 개발에 사용하지 않은 별도 지도에서 최종 평가할 계획입니다. 결과는 비교 지표, 그래프 및 주행 궤적 이미지로 정리합니다. 이 개요는 향후 실험 계획을 포함하며 모든 지도 조건의 검증이 완료되었다는 뜻은 아닙니다.

### 결과와 버전 관리

기능 구현, 관련 테스트, 실험 결과와 문서 정리를 의미 있는 단위로 커밋합니다. 소스 코드, 지도·실험 설정, 요약 결과와 대표 이미지는 저장소에서 관리합니다. 대용량 원본 데이터는 별도로 보관하고 실험 재현 방법을 문서화합니다.

<details>
<summary>English overview</summary>

## Project Overview

RacePlan is a 2D driving simulation project that compares Dijkstra, A*, and Hybrid A* on the same physical maps and under the same vehicle conditions. It investigates how corridor width, obstacle layout, turns, and grid resolution affect path planning and vehicle driving performance.

A planned path may still lead to a collision or a stop because of the vehicle's size and steering constraints. The project therefore **evaluates planning success and actual goal arrival separately**. A run reaches the goal when the rear-axle center enters within 0.5 m of the goal position without a collision; final heading is not required.

### Planners and simulation

- **Dijkstra and A*** use grid-based planning on a map with obstacles inflated to account for vehicle size.
- **Hybrid A*** considers vehicle position, heading, and steering constraints and checks collisions against the rectangular vehicle footprint.
- Paths are driven in a shared simulator that models vehicle steering and motion. Differences in how the planners account for obstacles are considered when interpreting results.

### Experimental conditions

The baseline experiments change one map characteristic at a time while keeping the other conditions fixed:

- **Basic environment:** Open or sufficiently spacious maps to assess baseline performance.
- **Corridor width:** Progressively narrower passages to compare planning, passage, and collision outcomes.
- **Obstacle layout:** Single, consecutive, and alternating obstacles to assess detours and repeated steering.
- **Turns:** Gentle and sharp direction changes to assess steering constraints and path tracking.
- **Grid resolution:** Different cell sizes for the same physical environment to compare map representation and search cost.
- **Start and goal conditions:** Different positions and initial headings on the same map.

Driving control is compared under basic path tracking, obstacle-aware slowing and stopping, and restart and replanning after a stop. These comparisons use the same initial path; replanning count and additional computation time are recorded when the path changes. The control policy for the main map comparisons will be fixed before the experiments.

Vehicle geometry and performance, start and goal, controller settings, noise configuration, and seeds are held consistent for each comparison. Runs use multiple seeds, and search-node limits, time limits, and actual computation time are recorded. Exact condition levels and repetition counts will be decided later.

### Evaluation metrics

- Goal arrival and collision rates; planning failures, timeouts, and recovery failures
- Path length, goal arrival time, and path-planning computation time
- Minimum obstacle clearance and path-tracking error
- Stopped time, restart and replanning counts, and additional computation time

Driving times are also compared among successful runs so that early termination of a failure is not mistaken for better performance. Simulated driving time and actual planning computation time are reported separately.

### Expected outcomes and future work

The study aims to identify how map characteristics affect planner performance and how steering constraints and driving control affect goal arrival. It will also examine the relationship between grid resolution, path representation, and computation cost.

Settings will be adjusted using development maps, then held fixed for final evaluation on separate maps not used during development. Results will be presented with comparison metrics, charts, and trajectory images. These experiments are planned; validation across all listed map conditions is not yet complete.

### Results and version control

Implementation, relevant tests, experimental results, and documentation are committed in meaningful units. The repository tracks source code, map and experiment settings, summary results, and representative images. Large raw datasets are stored separately, and reproduction steps are documented.

</details>

F1TENTH-style 2D simulation experiments comparing Dijkstra, A*, and Hybrid A*
under shared map, vehicle, controller, and metric conditions. The comparison is
the baseline for multi-condition objective optimization and reproducible
experiments with improved planner variants. Camera/CV perception is a later
extension, not part of the current core.

The project provides baseline planners, a shared closed-loop simulator, and
paired simulation-seed batch execution. A small synthetic research cycle is complete; larger unseen-map validation remains future work.

## 현재 상태 (2026-10-13)

- 성공은 충돌 없이 **후륜 축 중심이 목표 위치 0.5m 이내 진입**하는 것이다.
  최종 방향은 참고값이며 완전 정차를 요구하는 기준은 아니다.
- 전륜 조향 bicycle model이며 차량 전체 직사각형으로 충돌을 검사한다.
- 전체 테스트 **71개 통과**. 접근 감속 및 장애물 감속·정지 옵션을 구현했다.
- 최신 144건 비교에서 Dijkstra/A*는 각각 24/24 도달을 유지했다.
  Hybrid A*는 충돌 9→0, 성공 15→6, 시간초과 0→18이었다.
  정지로 충돌을 줄였지만 도달 성능 개선은 아니다.
- 다음은 정지 원인 분석과 안전한 재계획이다. 기존 validation 재사용 결과이며
  새로운 미사용 지도 평가가 아니다.

[인계 문서](docs/HANDOFF.md) · [최신 결과](docs/OBSTACLE_GUARD_20261013.md) ·
[커밋 구성](docs/COMMIT_PLAN.md) · [결과 폴더](results/README.md)

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe results/obstacle_guard_diagnostic.py
```

진단 스크립트는 기존 출력 폴더가 있으면 덮어쓰지 않고 실패한다. 제어 옵션은
Python API/진단 스크립트에서 사용하며 기존 CLI에 자동 적용하지 않는다.

## Quick start

```bash
uv sync --python 3.13 --extra dev
uv run --python 3.13 python -m pytest
```

Alternatively, use Python 3.11 or newer with `python -m pip install -e
".[dev]"`. The lockfile is the authoritative dependency snapshot for
reproducible development runs.

Compare the implemented planners on the included scenario:

```bash
uv run --python 3.13 raceplan-compare scenarios/demo.yaml
```

Apply the same obstacle clearance to all planners with, for example,
`--inflation-radius 0.5`.

Render the current paths and metrics as a PNG:

```bash
uv run --python 3.13 raceplan-plot scenarios/demo.yaml
```

Run the development closed-loop experiment and write one CSV row per planner:

```bash
uv run --python 3.13 raceplan-run scenarios/demo.yaml \
  --output results/raw/development.csv
```

This command holds the vehicle geometry, Pure Pursuit tracker, speed PID,
command limits, simulation step, and goal tolerance fixed. Noise is zero by
default. All planners drive from the scenario start, independent of the first
planned waypoint.

Run a paired development batch (example noise levels, not validated settings):

```bash
uv run --python 3.13 raceplan-run scenarios/demo.yaml \
  --simulation-seeds 0 1 2 --planners dijkstra astar hybrid_astar \
  --initial-position-std-m 0.02 --initial-yaw-std-rad 0.01 \
  --initial-speed-std-mps 0.01 --steering-std-rad 0.01 \
  --speed-measurement-std-mps 0.02 --output results/raw/pilot.csv
```

Each invocation writes a summary CSV plus `_trajectory.csv`, `_paths.csv`, and
`_manifest.json` beside it. IDs join episodes to trajectories and shared plans
within that invocation; use the manifest/output name when combining batches.
Existing output artifacts are rejected to preserve earlier episodes. Planning
failures have summary rows and no trajectory; collision and timeout episodes
retain all samples. A manifest left `running` indicates an incomplete batch.

Each planner plans once, then reuses that plan across simulation seeds. Repeated
planning times in the summary refer to the same measurement, not independent
timing samples. The manifest records settings, map hashes, source hashes, and
runtime versions. Wall-clock planning times and timeout outcomes can still vary
with machine load.

Noise uses independent Gaussian streams for initial state, steering actuation,
and speed measurement. Initial x/y perturbations are independent in world axes;
initial speed is perturbed around zero and clipped to vehicle speed limits.
Steering noise is added before actuator clipping; speed measurement noise feeds
the PID without changing ground-truth speed directly. Streams reset per episode
so matching seeds pair the initial perturbation and disturbances at each time
step across planners. This is a fixed-step development noise model, not a
calibrated sensor model. Pose sensing is otherwise exact. Trajectory controls
record the applied clipped values for the interval ending at each sample;
the initial sample has zero controls.

## Configuration conventions

Scenario YAML contains `name`, `map`, `[x, y, yaw]` start and goal poses,
`map_seed`, `simulation_seed`, and `timeout_s`. Use `map_seed: null` for fixed
maps. A non-null map seed records generation provenance only; this runner loads
the supplied map and does not generate it. `simulation_seed` affects driving
noise only. Both seeds must be non-negative integers (except nullable map seed).
The old `seed` key is no longer accepted. Paths are resolved relative to the
scenario file and unknown keys are rejected. `timeout_s` limits planning;
the shared simulation duration is recorded separately in the manifest.

Map YAML follows the ROS map-server grayscale convention and additionally
requires `source` and `license` provenance. Unknown cells are treated as
occupied. Obstacle inflation uses one metric radius and must not duplicate
clearance already encoded in a map.

`Pose2D` is referenced at the rear-axle centre. Hybrid A* checks an oriented
rectangular footprint at every sampled primitive pose; touching an obstacle or
leaving the map counts as collision. Grid planners instead operate on the
shared inflated grid, so experiments record this representation difference.

## Implemented

- Immutable occupancy grid and explicit world/grid coordinate conversion
- Shared planner input/output types with typed failure states
- Comparable 8-connected Dijkstra and A* implementations
- Diagonal corner-cutting prevention, timeout handling, and unit tests
- Strict scenario YAML and provenance-aware ROS-style image-map loading
- Shared metric obstacle inflation and a repository demo scenario
- Baseline Hybrid A* search with rear-axle vehicle geometry, bicycle-model
  primitives, goal-pose tolerances, and oriented footprint collision checks
- Fixed Pure Pursuit path tracker with anti-windup speed PID
- Fixed-step kinematic bicycle simulation with footprint collision checks
- Closed-loop reach, collision, completion-time, tracking-error, and steering
  metrics exported to CSV

Paired seed batches, driving noise, trajectory/path artifacts, and configuration
manifests are implemented. The historical initial development slice passed 40 tests and
a two-map seed pilot; see `docs/REPEATABILITY_IMPLEMENTATION.md` for limits.
Later work added synthetic map suites, aggregation, and a clearance-cost A* candidate.
Large randomized-map validation remains future work.

## Project documents

The end-to-end synthetic research cycle is documented in
[docs/RESEARCH_CYCLE_20261013.md](docs/RESEARCH_CYCLE_20261013.md): 52 tests,
335 episode records, frozen validation choice, held-out evaluation, ablation,
failure images, and a source/data reproduction package. The tested clearance-cost
candidate did **not** improve success rates; general superiority is not claimed.

```bash
python results/research_all.py --name research_new_run
```

This historical protocol uses pose-based scoring; it is not the current
position-only diagnostic. Resume requires matching source/config hashes.
Current code cannot resume the archived research_20261013 run: use its local ZIP
for historical source/data. A new name runs new data with current code.
Raw data and reproduction ZIPs are local-only and excluded from Git.

Controlled gate-width validation pilot: [docs/CORRIDOR_WIDTH.md](docs/CORRIDOR_WIDTH.md).
Five widths at fixed 0.1 m grid resolution, with a reproducible runner and failure
report (46 tests passed; 90 episode records including planning failures).

Saved-batch geometry and paired analysis (42 tests passed; two saved noise batches analyzed):

```bash
python -m raceplan.analyze results/raw/pilot_20261012/demo_noise.csv --output-dir results/analysis/geometry_20261012/demo_noise
```

Metric definitions, limitations, and outputs: [docs/GEOMETRY_ANALYSIS.md](docs/GEOMETRY_ANALYSIS.md).

Recorded driving footprint clearance is also analyzed (44 tests passed), including
collision/timeout episodes and per-step distances. See
[docs/DRIVING_CLEARANCE.md](docs/DRIVING_CLEARANCE.md) for the comparison image and findings.

- [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md): development, experiment, and
  research-analysis tracks, evaluation rules, and the next work package
- [`docs/LITERATURE_GAP.md`](docs/LITERATURE_GAP.md): related work, limitations,
  and the candidate research gap
- [`maps/README.md`](maps/README.md): map provenance and format notes

