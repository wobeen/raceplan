# RacePlan

F1TENTH-style 2D simulation experiments comparing Dijkstra, A*, and Hybrid A*
under shared map, vehicle, controller, and metric conditions. The comparison is
the baseline for multi-condition objective optimization and reproducible
experiments with improved planner variants. Camera/CV perception is a later
extension, not part of the current core.

The project is currently in its foundation stage. The first implemented pieces
are dependency-light core types, occupancy-grid handling, coordinate
conversion, and a common planner contract.

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

Apply the same obstacle clearance to both planners with, for example,
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
command limits, simulation step, and goal tolerance fixed. The scenario seed is
recorded in the CSV; the current deterministic demo does not yet inject noise.

## Configuration conventions

Scenario YAML contains `name`, `map`, `[x, y, yaw]` start and goal poses,
`seed`, and `timeout_s`. Paths are resolved relative to the scenario file and
unknown keys are rejected. The current single `seed` field is recorded but not
used; the next development slice will replace it with explicit map and
simulation seed semantics.

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

Randomized map suites, noise models, batch aggregation, and optimized planner
variants remain future milestones.

## Project documents

- [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md): development, experiment, and
  research-analysis tracks, evaluation rules, and the next work package
- [`docs/LITERATURE_GAP.md`](docs/LITERATURE_GAP.md): related work, limitations,
  and the candidate research gap
- [`maps/README.md`](maps/README.md): map provenance and format notes

