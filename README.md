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

## Implemented

- Immutable occupancy grid and explicit world/grid coordinate conversion
- Shared planner input/output types with typed failure states
- Comparable 8-connected Dijkstra and A* implementations
- Diagonal corner-cutting prevention, timeout handling, and unit tests

Hybrid A*, map-file loading, simulation, metrics, and batch experiments remain
future milestones.

See [`docs/RESEARCH_PLAN.md`](docs/RESEARCH_PLAN.md) for the research questions,
experimental design, and completion criteria.

