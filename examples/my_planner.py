"""Replace the plan method to compare your own algorithm with the baselines."""
from raceplan.planners import AStarPlanner
from raceplan.planners.base import Planner


class MyPlanner(Planner):
    @property
    def name(self):
        return 'my_planner'

    def plan(self, grid, start, goal, *, timeout_s=None):
        # Example only: replace this call with your own implementation.
        return AStarPlanner().plan(grid, start, goal, timeout_s=timeout_s)
