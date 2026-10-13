import json
from pathlib import Path
import numpy as np
from raceplan.corridor_suite import WIDTH_CELLS, corridor_grid, generate, START, GOAL
from raceplan.common import load_scenario, load_occupancy_map, footprint_in_collision
from raceplan.defaults import baseline_vehicle


def test_gate_family_changes_only_width_and_preserves_query(tmp_path):
    root = tmp_path/'family'
    family = json.loads(generate(root).read_text())
    previous = None
    for member, width in zip(family['members'], WIDTH_CELLS):
        scenario = load_scenario(root/member['scenario'])
        grid = load_occupancy_map(scenario.map_path).grid
        assert grid.resolution == 0.1
        assert np.array_equal(grid.occupied, corridor_grid(width))
        assert np.count_nonzero(~grid.occupied[:, 40]) == width
        assert [scenario.start.x, scenario.start.y, scenario.start.yaw] == START
        assert [scenario.goal.x, scenario.goal.y, scenario.goal.yaw] == GOAL
        assert not footprint_in_collision(grid, scenario.start, baseline_vehicle())
        assert not footprint_in_collision(grid, scenario.goal, baseline_vehicle())
        if previous is not None:
            assert np.all(grid.occupied | ~previous)
            changed = grid.occupied != previous
            assert not changed[:, :30].any() and not changed[:, 50:].any()
        previous = grid.occupied
