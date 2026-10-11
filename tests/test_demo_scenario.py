from pathlib import Path

import pytest

from raceplan.common import PlannerStatus, load_occupancy_map, load_scenario
from raceplan.planners import AStarPlanner, DijkstraPlanner


def test_repository_demo_loads_and_both_planners_agree() -> None:
    root = Path(__file__).resolve().parents[1]
    scenario = load_scenario(root / "scenarios" / "demo.yaml")
    map_metadata = load_occupancy_map(scenario.map_path)

    dijkstra = DijkstraPlanner().plan(
        map_metadata.grid,
        scenario.start,
        scenario.goal,
        timeout_s=scenario.timeout_s,
    )
    astar = AStarPlanner().plan(
        map_metadata.grid,
        scenario.start,
        scenario.goal,
        timeout_s=scenario.timeout_s,
    )

    assert dijkstra.status is PlannerStatus.SUCCESS
    assert astar.status is PlannerStatus.SUCCESS
    assert dijkstra.path is not None and astar.path is not None
    assert astar.path.cost == pytest.approx(dijkstra.path.cost)
    assert astar.expanded_nodes <= dijkstra.expanded_nodes
