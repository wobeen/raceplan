"""Bounded forward arc + clearance-aware Hybrid tails for recovery only.

Candidate order is fixed before evaluation. No map-specific tuning, reverse
motion, pose relocation, or reduction of the physical-body clearance check.
"""
from dataclasses import replace
from collections import OrderedDict
from time import perf_counter

from raceplan.common import Path, PlannerResult, PlannerStatus, footprint_in_collision
from raceplan.metrics import Clearance
from .hybrid_astar import HybridAStarPlanner
from .hybrid_primitives import rollout_bicycle


class _ExactClearanceCache:
    """Request-local bounded cache; keys retain full pose/vehicle precision."""
    def __init__(self, grid, max_entries=32768):
        self.clearance = Clearance(grid)
        self.values = OrderedDict()
        self.max_entries = max_entries
        self.hits = self.misses = 0

    def footprint(self, pose, vehicle):
        key = (pose.x, pose.y, pose.yaw, vehicle)
        if key in self.values:
            self.hits += 1
            self.values.move_to_end(key)
            return self.values[key]
        self.misses += 1
        value = self.clearance.footprint(pose, vehicle)
        self.values[key] = value
        if len(self.values) > self.max_entries:
            self.values.popitem(last=False)
        return value


def forward_alternatives(algorithm, grid, pose, goal, *, minimum_clearance=.02,
                         timeout_s=3.0, policy_version=3):
    """Yield at most 15 candidates with per-tail time and deterministic node bounds.

    Longer initial arcs protect the PP lookahead from an abrupt Hybrid tail turn.
    Clearance and steering costs change tail selection, leaving baseline intact.
    Failed arc checks are emitted too so diagnostics expose the complete budget.
    """
    config = replace(algorithm.config, clearance_cost_weight=.15,
                     steering_cost_weight=.5, max_expanded_nodes=4000,
                     primitives=replace(algorithm.config.primitives, allow_reverse=False))
    tail_planner = HybridAStarPlanner(algorithm.vehicle, config)
    optimized = policy_version == 4
    request_started = perf_counter()
    clearance = _ExactClearanceCache(grid) if optimized else Clearance(grid)
    request_spent = perf_counter() - request_started
    # Fixed request budget: three ordinary planning timeouts in total, rather
    # than fifteen independent timeouts. Includes arc/cache setup and checks;
    # each individual geometry operation can overrun this cooperative deadline.
    remaining_nodes = 4000
    request_budget = 3 * timeout_s
    maximum = config.primitives.max_steering_angle
    for distance in (1.5, .75, 2.5):
        for steering in (0.0, -.5*maximum, .5*maximum, -maximum, maximum):
            started = perf_counter()
            prefix = rollout_bicycle(pose, steering_angle=steering,
                                     signed_distance=distance,
                                     wheelbase=algorithm.vehicle.wheelbase,
                                     sample_distance=min(.05, config.primitives.sample_distance))
            metadata = dict(prefix_distance_m=distance, prefix_steering_rad=steering,
                            clearance_cost_weight=.15, steering_cost_weight=.5,
                            max_expanded_nodes=4000)
            if optimized:
                metadata.update(request_node_budget=4000, request_time_budget_s=request_budget,
                                clearance_cache_hits=clearance.hits,
                                clearance_cache_misses=clearance.misses)
                if remaining_nodes <= 0 or request_spent + perf_counter()-started >= request_budget:
                    yield PlannerResult(PlannerStatus.TIMEOUT,
                                        planning_time_s=perf_counter()-started,
                                        metadata={**metadata, 'reason': 'request_budget_exhausted'})
                    return
            if any(footprint_in_collision(grid, p, algorithm.vehicle)
                   or clearance.footprint(p, algorithm.vehicle) < minimum_clearance
                   for p in prefix):
                request_spent += perf_counter()-started
                yield PlannerResult(PlannerStatus.NO_PATH,
                                    planning_time_s=perf_counter()-started,
                                    metadata={**metadata, 'reason': 'prefix_clearance_blocked'})
                continue
            if optimized:
                remaining_time = request_budget - (request_spent + perf_counter()-started)
                if remaining_time <= 0:
                    yield PlannerResult(PlannerStatus.TIMEOUT,
                                        planning_time_s=perf_counter()-started,
                                        metadata={**metadata, 'reason': 'request_budget_exhausted'})
                    return
                tail_planner = HybridAStarPlanner(algorithm.vehicle,
                    replace(config, max_expanded_nodes=remaining_nodes))
                tail = tail_planner.plan(grid, prefix[-1], goal,
                    timeout_s=min(timeout_s, remaining_time), clearance_evaluator=clearance)
                remaining_nodes -= tail.expanded_nodes
                metadata.update(clearance_cache_hits=clearance.hits,
                                clearance_cache_misses=clearance.misses)
            else:
                tail = tail_planner.plan(grid, prefix[-1], goal, timeout_s=timeout_s)
            path = (Path(prefix + tail.path.poses[1:], distance+tail.path.cost)
                    if tail.path is not None else None)
            request_spent += perf_counter()-started
            yield PlannerResult(tail.status, path, tail.expanded_nodes,
                                perf_counter()-started, {**metadata, **tail.metadata})
