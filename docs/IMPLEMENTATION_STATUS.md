# Implementation status

Updated: 2026-10-11

## Completed

- Python `src/` package and locked development environment
- Core `Pose2D`, `Path`, `PlannerResult`, and failure status contracts
- Immutable occupancy grid with world/grid conversion
- Common `Planner` interface
- Dijkstra and A* using the same 8-connected motion model
- Diagonal corner-cutting prevention and timeout/failure reporting
- Unit tests for core contracts, grid boundaries, optimal-cost equivalence,
  corner cases, and failure states
- Strict scenario YAML loading and relative path resolution
- ROS-style grayscale map loading with source/licence metadata
- Shared metric obstacle inflation
- Repository demo map and end-to-end loading/planning test
- Rear-axle-referenced vehicle geometry
- Exact constant-steering bicycle-model primitive rollout
- Configurable forward/reverse and steering primitive sets
- Oriented rectangular footprint collision checks along full primitives
- Hybrid A* `(x, y, yaw)` search, goal-pose test, and path reconstruction
- Three-planner development comparison on the demo map

Current verification: **36 tests passed** with Python 3.13.

## Next milestone

Begin the common tracking and simulation slice:

1. Define a shared kinematic bicycle simulation step.
2. Implement one fixed path tracker and command limits.
3. Run all three paths through the same vehicle model.
4. Record reach, collision, tracking error, and completion time.

## Local environment note

The pre-existing Windows Python launchers report incomplete installation paths.
The project was therefore verified in the `.venv` managed by `uv` with Python
3.13. This does not affect the tests, but the machine-level Python installation
should be repaired before relying on bare `python` or `pip` commands.
