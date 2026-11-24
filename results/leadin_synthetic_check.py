"""Planning-only check of the lead-in rescue on the synthetic wall-ahead grids.

These grids were the only inputs used to design the candidate (see
docs/LEADIN_RESCUE_DEVELOPMENT.md).  No simulation is run.  Prints a JSON
summary of base acceptance, rescue outcomes per variant, and planning time.
"""
from __future__ import annotations

from collections import Counter
from itertools import product
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from raceplan.common import OccupancyGrid, Pose2D
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
WALL_COLUMNS = (8, 10, 12)        # wall x = 1.6/2.0/2.4 m, three cells thick
WALL_BOTTOM_ROWS = (8, 10, 12)    # wall from y = 1.6/2.0/2.4 m to the top border
START_Y = (5.0, 5.6, 6.2)
GOAL_Y = (1.1, 6.1)
CLASSES = ('LeadInRescueK3', 'LeadInRescueK6', 'LeadInStraight')


def grid(column, bottom_row):
    occupied = np.zeros((36, 52), dtype=bool)
    occupied[[0, -1], :] = occupied[:, [0, -1]] = True
    occupied[bottom_row:, column:column + 3] = True
    return OccupancyGrid(occupied, 0.2)


def main():
    base = load_custom_planner(f"{ROOT / 'examples/smoothed_astar_planner.py'}:SmoothedLowClearance")[0]
    planners = [load_custom_planner(f"{ROOT / 'examples/leadin_rescue_planner.py'}:{name}")[0]
                for name in CLASSES]
    base_outcomes, rescue, slowest = Counter(), Counter(), Counter()
    for column, row, start_y, goal_y in product(WALL_COLUMNS, WALL_BOTTOM_ROWS, START_Y, GOAL_Y):
        occupancy = grid(column, row)
        start, goal = Pose2D(1.1, start_y, 0.0), Pose2D(9.3, goal_y)
        first = base.plan(occupancy, start, goal, timeout_s=2.0)
        base_outcomes[first.metadata.get('smoothing'), first.metadata.get('smoothing_reason', '')] += 1
        for planner in planners:
            began = perf_counter()
            result = planner.plan(occupancy, start, goal, timeout_s=2.0)
            slowest[planner.name] = max(slowest[planner.name], (perf_counter() - began) * 1000)
            rescue[planner.name, result.metadata.get('rescue')] += 1
    print(json.dumps({
        'cases': len(WALL_COLUMNS) * len(WALL_BOTTOM_ROWS) * len(START_Y) * len(GOAL_Y),
        'base': {f'{k[0]}:{k[1]}': v for k, v in sorted(base_outcomes.items())},
        'rescue': {f'{k[0]}:{k[1]}': v for k, v in sorted(rescue.items())},
        'max_planning_ms': {k: round(v, 1) for k, v in sorted(slowest.items())},
    }, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
