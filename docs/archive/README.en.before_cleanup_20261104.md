<p align="center"><a href="README.md">한국어</a> | <strong>English</strong></p>

# RacePlan

### Compare your own planner

Copy [`examples/my_planner.py`](examples/my_planner.py), implement `Planner.name` and
`plan(grid, start, goal, *, timeout_s=None)`, and return a `PlannerResult`. A successful
result contains a `Path` of world-coordinate `Pose2D` points in metres. The example
delegates to A* only to demonstrate integration; replace it with your own algorithm.

```powershell
python -m raceplan.experiment scenarios/demo.yaml --custom-planner examples/my_planner.py:MyPlanner --simulation-seeds 0 1 2 --output results/raw/my_comparison.csv
python -m raceplan.custom_report results/raw/my_comparison.csv --output results/figures/my_comparison.png
```

The baselines and your planner use the same map, vehicle, controller and seeds. Use
`--planners` to select baselines and repeat `--custom-planner` to add several custom
planners with distinct names. The manifest records the custom file path and SHA-256;
JSON-compatible mapping/dataclass `config` values are preserved; convert paths and arrays
to strings and lists. Unsupported settings are rejected before result creation. The
summary, path and trajectory CSVs are saved. The PNG shows the first seed. The
outcome counts cover every seed; `--seed 1` selects the displayed trajectory. The report
uses the recorded query and checks map hashes without replanning or resimulation. Existing
outputs are not overwritten. This development runner uses the same inflated map for
planning and simulation, and planner costs are not necessarily geometric path lengths.
Planning times are reported by each planner; the runner does not measure wall time.
Loading a custom Python file executes it: only load trusted files.
See [`docs/CUSTOM_PLANNER_COMPARISON.md`](docs/CUSTOM_PLANNER_COMPARISON.md) for the
interface, failure behavior, analysis commands, and follow-up plan (in Korean).
For a self-contained search example, see [`examples/turn_aware_planner.py`](examples/turn_aware_planner.py):
direction-state A* with a fixed turn cost and a zero-weight ablation. Its objective, limitations,
and development comparison command are in [`docs/TURN_AWARE_CANDIDATE.md`](docs/TURN_AWARE_CANDIDATE.md).
The sealed, fixed-candidate validation/evaluation protocol is documented in
[`docs/TURN_AWARE_HOLDOUT.md`](docs/TURN_AWARE_HOLDOUT.md) (in Korean).

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

For installation, command examples, and detailed project documentation, see the [main README](README.md#quick-start).
