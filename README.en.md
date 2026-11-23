<p align="center"><a href="README.md">한국어</a> | <strong>English</strong></p>

# RacePlan

Compare Dijkstra, A*, Hybrid A*, and your own planner in a shared 2D vehicle
simulation. Save planned paths, driven trajectories, outcomes, and metrics.

## Core workflow

Use Python 3.11 or newer in Windows PowerShell. From the repository root, create a fresh
virtual environment, run the demo and example suite, then generate HTML from the saved suite.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[dev]"
.\.venv\Scripts\raceplan-workflow.exe scenarios/demo.yaml --simulation-seeds 0 1 2 --output-dir results/raw/comparison
.\.venv\Scripts\raceplan-suite.exe examples/suite.yaml --output-dir results/raw/my_suite
.\.venv\Scripts\raceplan-report.exe results/raw/my_suite --output-dir results/reports/my_suite
```

To install locked dependencies with `uv`, replace the first two commands with
`uv sync --locked --python 3.13 --extra dev --no-editable`. The examples read their maps,
scenarios, configuration, and custom planner from the repository.

`raceplan-workflow` runs the comparison, analyzes saved results, and renders a PNG.
Choose a new `--output-dir` for each run. Outputs are `comparison.csv`, path and trajectory
CSVs, a manifest, `analysis/`, `comparison.png`, and per-phase status in `workflow.json`.

PNG counts cover every seed; `--report-seed N` selects the displayed trajectory.
`--baseline astar` selects the analysis reference. The default is A* when selected,
otherwise the first selected baseline. `--spacing 0.1` controls analysis path sampling
in metres. The runner's noise and `--inflation-radius` options are supported.

Input and seed errors are rejected before execution where possible. Custom baseline
names are checked against the completed manifest so custom code is imported only once.
On failure, later phases stop; `workflow.json` records `failed_phase` and partial outputs
remain available. There is no automatic retry in the same folder. Lower-level output
arguments such as `--output` are not accepted by the workflow command.

To analyze or render existing results independently:

```powershell
.\.venv\Scripts\raceplan-analyze.exe results/raw/comparison/comparison.csv --baseline astar --output-dir results/analysis/reanalysis
.\.venv\Scripts\python.exe -m raceplan.custom_report results/raw/comparison/comparison.csv --seed 1 --output results/figures/selected_seed.png
```

The shared simulator uses Pure Pursuit, speed PID, a bicycle model, and rectangular
vehicle collision checks. Success means reaching within 0.5 m of the goal with no
collision; final heading is descriptive. Obstacle guard and recovery are disabled
in the default runner.

`raceplan-report` also accepts a saved single-workflow folder. Open the generated
`index.html` and copy the whole report folder to share the HTML and its local PNGs.
Coverage, denominators, and deterministic selection are documented in the
[saved report guide](docs/SAVED_REPORT.md) (Korean).

## Multiple scenarios

The YAML applies common settings to sequential case workflows and writes combined
episodes, deduplicated planning, paired data, and case/overall summaries. Relative paths
are resolved from the config file. Failed cases preserve partial outputs and explicit
missing coverage; ordinary case errors allow later cases to run and produce a nonzero
final exit. See the [schema and interruption policy](docs/SUITE.md) (Korean).

## Your planner

Copy [examples/my_planner.py](examples/my_planner.py), implement `Planner.name`
and `plan(grid, start, goal, *, timeout_s=None)`, and return a `PlannerResult`.
Successful paths contain world-coordinate poses in metres and radians.
The template delegates to A* to demonstrate integration.

```powershell
.\.venv\Scripts\raceplan-workflow.exe scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output-dir results/raw/custom
```

Select baselines using `--planners astar hybrid_astar`; repeat `--custom-planner`
for multiple implementations with distinct names. Loading a Python file executes
it, so use trusted code. See the [interface guide](docs/CUSTOM_PLANNER_COMPARISON.md)
(in Korean) for configuration and failure handling.
Ordinary custom `plan` exceptions and invalid results are recorded as `planning_error`
with an error type/message for every seed; the remaining comparison continues. Long diagnostics
are bounded and marked as truncated. Import/config
errors and builtin bugs still stop execution. `KeyboardInterrupt` and `SystemExit` are not
converted into planning failures. Workflow `complete` means processing finished, not that
every planner reached the goal.

## Interpretation

Every planner and simulation uses the same inflated grid; inflation defaults to
zero. Grid planners check point connectivity, while Hybrid A* checks an oriented
vehicle footprint. Planning representations therefore differ.

Each planner plans once and reuses its path across seeds. `planning_time_ms` remains
planner-reported. `runner_planning_time_ms` measures wall time around the plan call only,
excluding loading, grid copies, result validation, and driving. Both values are reused
across seeds, not independent timing samples. Legacy batches show runner timing as n/a.
The legacy `path_cost_m` column
contains planner-defined cost; analysis computes geometric length separately.
Custom planner timeouts require cooperation from the implementation.

The manifest records settings, source hashes, map provenance, and environment.
Summary, path, and trajectory CSVs preserve planning failures and driving outcomes.
See [map conventions](maps/README.md) for map inputs.

Run `.\.venv\Scripts\python.exe -m pytest -q` after installation. The last full verification passed 130 tests.
Experimental candidates and historical runners are indexed separately in
[feature scope](docs/FEATURE_SCOPE.md) (Korean), [results](results/README.md), and
[handoff](docs/HANDOFF.md). Earlier README content is retained under
[docs/archive](docs/archive/README.en.before_cleanup_20261104.md).
