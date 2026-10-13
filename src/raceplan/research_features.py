"""Query descriptors independent of the compared planner's chosen route."""
from heapq import heappop, heappush
from math import hypot, sqrt
import numpy as np
from raceplan.common.planning_space import center_clearance
from raceplan.planners import AStarPlanner
from raceplan.planners._grid_search import _neighbours


def descriptors(grid,start,goal,vehicle):
    distance=center_clearance(grid)
    first,last=grid.world_to_grid(start.x,start.y),grid.world_to_grid(goal.x,goal.y)
    capacity=np.maximum(0,distance-grid.resolution/sqrt(2))
    best={first:float(capacity[first])}; queue=[(-best[first],first)]
    widest=None
    while queue:
        neg,cell=heappop(queue); value=-neg
        if value!=best[cell]:continue
        if cell==last:
            widest=value;break
        for other,_ in _neighbours(grid,cell):
            score=min(value,float(capacity[other]))
            if score>best.get(other,-1):
                best[other]=score;heappush(queue,(-score,other))
    reference=AStarPlanner().plan(grid,start,goal,timeout_s=3)
    direct=hypot(goal.x-start.x,goal.y-start.y)
    return dict(obstacle_density=float(grid.occupied.mean()),
        widest_grid_disk_diameter_m=None if widest is None else 2*widest,
        widest_grid_disk_vehicle_widths=None if widest is None else 2*widest/vehicle.width,
        reference_detour=None if reference.path is None or not direct else reference.path.cost/direct,
        reference_status=reference.status.value,
        note='Widest whole-cell disk route lower bound, not exact geometric bottleneck; point A* detour reference.')
