<p align="center"><a href="README.md">한국어</a> | <strong>English</strong></p>

# RacePlan

Compare Dijkstra, A*, Hybrid A*, and your own planner in a shared 2D vehicle
simulation. Save planned paths, driven trajectories, outcomes, and metrics.

## Core workflow

Python 3.11 or newer, from the repository root:

```powershell
python -m pip install -e ".[dev]"
python -m raceplan.experiment scenarios/demo.yaml --simulation-seeds 0 1 2 --output results/raw/comparison.csv
python -m raceplan.analyze results/raw/comparison.csv --baseline astar --output-dir results/analysis/comparison
python -m raceplan.custom_report results/raw/comparison.csv --output results/figures/comparison.png
```

Use new output names for each run; existing results are rejected.
Analysis and reporting read saved artifacts. PNG outcome counts cover every seed;
the first seed is displayed by default, with `--seed N` available.

The shared simulator uses Pure Pursuit, speed PID, a bicycle model, and rectangular
vehicle collision checks. Success means reaching within 0.5 m of the goal with no
collision; final heading is descriptive. Obstacle guard and recovery are disabled
in the default runner.

## Your planner

Copy [examples/my_planner.py](examples/my_planner.py), implement `Planner.name`
and `plan(grid, start, goal, *, timeout_s=None)`, and return a `PlannerResult`.
Successful paths contain world-coordinate poses in metres and radians.
The template delegates to A* to demonstrate integration.

```powershell
python -m raceplan.experiment scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output results/raw/custom.csv
python -m raceplan.custom_report results/raw/custom.csv --output results/figures/custom.png
```

Select baselines using `--planners astar hybrid_astar`; repeat `--custom-planner`
for multiple implementations with distinct names. Loading a Python file executes
it, so use trusted code. See the [interface guide](docs/CUSTOM_PLANNER_COMPARISON.md)
(in Korean) for configuration and failure handling.

## Interpretation

Every planner and simulation uses the same inflated grid; inflation defaults to
zero. Grid planners check point connectivity, while Hybrid A* checks an oriented
vehicle footprint. Planning representations therefore differ.

Each planner plans once and reuses its path across seeds. Planning time is
self-reported, not independent timing per seed. The legacy `path_cost_m` column
contains planner-defined cost; analysis computes geometric length separately.
Custom planner timeouts require cooperation from the implementation.

The manifest records settings, source hashes, map provenance, and environment.
Summary, path, and trajectory CSVs preserve planning failures and driving outcomes.
See [map conventions](maps/README.md) for map inputs.

Run `python -m pytest -q` after installation. The last full verification passed 91 tests.
Experimental candidates and historical runners are indexed separately in
[feature scope](docs/FEATURE_SCOPE.md) (Korean), [results](results/README.md), and
[handoff](docs/HANDOFF.md). Earlier README content is retained under
[docs/archive](docs/archive/README.en.before_cleanup_20261104.md).
