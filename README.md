# RacePlan

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

