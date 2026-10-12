from pathlib import Path

import numpy as np

from raceplan.common import OccupancyGrid, Path as PlannedPath, Pose2D
from raceplan.defaults import (
    baseline_simulation_config,
    baseline_tracker_config,
    baseline_vehicle,
)
from raceplan.experiment import main
from raceplan.simulator import SimulationStatus, run_episode


def test_fixed_controller_reaches_straight_goal() -> None:
    grid = OccupancyGrid(np.zeros((5, 8), dtype=bool), resolution=1.0)
    path = PlannedPath(
        (Pose2D(1.5, 2.5, 0.0), Pose2D(5.5, 2.5, 0.0)),
        cost=4.0,
    )

    result = run_episode(
        grid,
        path,
        path.poses[-1],
        baseline_vehicle(),
        baseline_tracker_config(),
        baseline_simulation_config(),
    )

    assert result.status is SimulationStatus.REACHED
    assert not result.collided
    assert result.tracking_rmse < 1e-9


def test_development_experiment_writes_one_row_per_planner(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "result.csv"

    exit_code = main(
        [str(root / "scenarios" / "demo.yaml"), "--output", str(output)]
    )

    lines = output.read_text(encoding="utf-8").splitlines()
    assert exit_code == 0
    assert len(lines) == 4
    assert all(name in output.read_text(encoding="utf-8") for name in (
        "dijkstra",
        "astar",
        "hybrid_astar",
    ))
