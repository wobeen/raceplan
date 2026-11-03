"""Intentional failures for demonstrating the custom-plan error reporting policy."""
from raceplan.planners.base import Planner


class ExceptionPlanner(Planner):
    name = 'example_exception'

    def plan(self, grid, start, goal, *, timeout_s=None):
        raise RuntimeError('intentional custom planning failure')


class InvalidResultPlanner(Planner):
    name = 'example_invalid_result'

    def plan(self, grid, start, goal, *, timeout_s=None):
        return None  # Deliberately violates the PlannerResult contract.
