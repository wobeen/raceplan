# RacePlan

F1TENTH-style 2D simulation experiments comparing Dijkstra, A*, and Hybrid A*
under shared map, vehicle, controller, and metric conditions. The comparison is
the baseline for multi-condition objective optimization and reproducible
experiments with improved planner variants. Camera/CV perception is a later
extension, not part of the current core.

The project provides baseline planners, a shared closed-loop simulator, and
paired simulation-seed batch execution. Research evaluation remains future work.

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
manifests are implemented. The current development slice passed 40 tests and
a two-map seed pilot; see `docs/REPEATABILITY_IMPLEMENTATION.md` for limits.
Randomized map suites, batch aggregation, and optimized planner variants remain
future milestones.

## Project documents

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

