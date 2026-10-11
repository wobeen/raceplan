# RacePlan

F1TENTH-style 2D simulation experiments comparing Dijkstra, A*, and Hybrid A*
under shared map, vehicle, controller, and metric conditions.

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

## Implemented

- Immutable occupancy grid and explicit world/grid coordinate conversion
- Shared planner input/output types with typed failure states
- Comparable 8-connected Dijkstra and A* implementations
- Diagonal corner-cutting prevention, timeout handling, and unit tests
- Strict scenario YAML and provenance-aware ROS-style image-map loading
- Shared metric obstacle inflation and a repository demo scenario
- Baseline Hybrid A* search with rear-axle vehicle geometry, bicycle-model
  primitives, goal-pose tolerances, and oriented footprint collision checks

Simulation, tracking control, metrics, and batch experiments remain future
milestones.

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for the research questions,
experimental design, and completion criteria.

