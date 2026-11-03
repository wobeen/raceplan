"""Contract and independent shortest-path checks for the custom candidate."""
import csv
import json
from heapq import heappop, heappush
from math import atan2, hypot, pi
from pathlib import Path

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, PlannerStatus, Pose2D
from raceplan.experiment import main
from raceplan.planners import AStarPlanner
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'examples/turn_aware_planner.py'


def candidate(classname='TurnAwareAStar'):
    return load_custom_planner(f'{PLUGIN}:{classname}')[0]


def oracle(grid, start, goal, weight):
    """Independent Dijkstra over incoming-edge states; no candidate helpers."""
    initial = (*grid.world_to_grid(start.x, start.y), start.yaw)
    target = grid.world_to_grid(goal.x, goal.y)
    queue, costs = [(0.0, initial)], {initial: 0.0}
    while queue:
        cost, state = heappop(queue)
        if cost != costs[state]:
            continue
        row, col, heading = state
        if (row, col) == target:
            return cost
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if (not dr and not dc) or not grid.is_free((row + dr, col + dc)):
                    continue
                if dr and dc and (not grid.is_free((row + dr, col)) or not grid.is_free((row, col + dc))):
                    continue
                yaw = atan2(dr, dc)
                turn = abs((yaw - heading + pi) % (2 * pi) - pi)
                other = (row + dr, col + dc, yaw)
                updated = cost + hypot(dr, dc) * grid.resolution + weight * turn
                if updated < costs.get(other, float('inf')):
                    costs[other] = updated
                    heappush(queue, (updated, other))
    return float('inf')


def test_turn_cost_matches_independent_direction_state_oracle_and_saved_geometry():
    occupied = np.zeros((7, 8), dtype=bool)
    occupied[1:6, 3] = True
    occupied[4, 3] = False
    grid = OccupancyGrid(occupied, 0.3, -1.0, 2.0)
    algorithm = candidate()
    for yaw in (0.0, 1.3, -pi):
        start, goal = grid.grid_to_world((1, 1), yaw), grid.grid_to_world((5, 6))
        result = algorithm.plan(grid, start, goal)
        assert result.status is PlannerStatus.SUCCESS
        assert result.path.cost == pytest.approx(oracle(grid, start, goal, 0.2))
        cells = [grid.world_to_grid(p.x, p.y) for p in result.path.poses]
        assert cells[0] == (1, 1) and cells[-1] == (5, 6)
        cost, heading = 0.0, yaw
        for first, second, pose in zip(cells, cells[1:], result.path.poses):
            dr, dc = second[0] - first[0], second[1] - first[1]
            assert max(abs(dr), abs(dc)) == 1 and grid.is_free(second)
            assert not (dr and dc) or (grid.is_free((first[0] + dr, first[1]))
                                      and grid.is_free((first[0], first[1] + dc)))
            edge_yaw = atan2(dr, dc)
            assert pose.yaw == pytest.approx(edge_yaw)
            cost += hypot(dr, dc) * grid.resolution + 0.2 * abs((edge_yaw - heading + pi) % (2*pi) - pi)
            heading = edge_yaw
        assert result.path.cost == pytest.approx(cost)
        assert result.planning_time_s > 0 and result.expanded_nodes > 0


def test_start_heading_changes_route_and_zero_weight_preserves_shortest_cost():
    grid = OccupancyGrid(np.zeros((4, 4), dtype=bool), 0.5)
    goal = grid.grid_to_world((1, 2))
    east = candidate().plan(grid, grid.grid_to_world((0, 0), 0.0), goal)
    diagonal = candidate().plan(grid, grid.grid_to_world((0, 0), pi / 4), goal)
    assert grid.world_to_grid(east.path.poses[1].x, east.path.poses[1].y) == (0, 1)
    assert grid.world_to_grid(diagonal.path.poses[1].x, diagonal.path.poses[1].y) == (1, 1)
    occupied = np.zeros((7, 8), dtype=bool)
    occupied[1:6, 3] = True
    for map_array in (grid.occupied, occupied):
        current = OccupancyGrid(map_array, 0.5)
        start, goal = current.grid_to_world((0, 0)), current.grid_to_world((current.height-1, current.width-1))
        assert candidate('LengthOnlyAStar').plan(current, start, goal).path.cost == pytest.approx(
            AStarPlanner().plan(current, start, goal).path.cost)


def test_expected_failure_contract_and_same_cell():
    grid = OccupancyGrid(np.array([[False, True], [True, False]]), 1.0)
    planner = candidate()
    start, goal = Pose2D(0.5, 0.5, 1.2), Pose2D(1.5, 1.5)
    assert planner.plan(grid, start, goal).status is PlannerStatus.NO_PATH
    assert planner.plan(grid, Pose2D(-0.5, 0.5), goal).status is PlannerStatus.INVALID_START
    assert planner.plan(grid, start, Pose2D(1.5, 0.5)).status is PlannerStatus.INVALID_GOAL
    timeout = planner.plan(grid, start, goal, timeout_s=0.0)
    assert timeout.status is PlannerStatus.TIMEOUT and timeout.expanded_nodes == 0
    same = planner.plan(grid, start, start)
    assert same.path.poses == (start,) and same.path.cost == 0


def test_candidate_and_ablation_run_through_public_comparison(tmp_path):
    output = tmp_path / 'turn.csv'
    assert main([str(ROOT/'scenarios/demo.yaml'), '--output', str(output), '--planners', 'astar',
                 '--custom-planner', f'{PLUGIN}:TurnAwareAStar',
                 '--custom-planner', f'{PLUGIN}:LengthOnlyAStar', '--simulation-seeds', '0', '1']) == 0
    with output.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6 and all(row['planning_status'] == 'success' for row in rows)
    manifest = json.loads(output.with_name('turn_manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'complete'
    assert manifest['planners']['turn_aware_astar']['config']['turn_weight_m_per_rad'] == 0.20
    assert manifest['planners']['turn_aware_zero']['config']['turn_weight_m_per_rad'] == 0.0
