"""Small development comparison for the implemented planners."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from raceplan.common import (
    VehicleGeometry,
    inflate_obstacles,
    load_occupancy_map,
    load_scenario,
)
from raceplan.planners import (
    AStarPlanner,
    DijkstraPlanner,
    HybridAStarConfig,
    HybridAStarPlanner,
)
from raceplan.planners.hybrid_primitives import MotionPrimitiveConfig


def _baseline_hybrid_astar() -> HybridAStarPlanner:
    """Return development defaults; official experiments will load config."""

    vehicle = VehicleGeometry(
        wheelbase=0.33,
        length=0.58,
        width=0.31,
        rear_axle_to_center=0.10,
    )
    config = HybridAStarConfig(
        xy_resolution=0.5,
        yaw_bins=36,
        goal_position_tolerance=0.5,
        goal_yaw_tolerance=0.35,
        primitives=MotionPrimitiveConfig(
            max_steering_angle=0.45,
            steering_samples=5,
            travel_distance=0.5,
            sample_distance=0.1,
            allow_reverse=False,
        ),
    )
    return HybridAStarPlanner(vehicle, config)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare Dijkstra and A* on one RacePlan scenario.",
    )
    parser.add_argument("scenario", type=Path, help="scenario YAML path")
    parser.add_argument(
        "--inflation-radius",
        type=float,
        default=0.0,
        metavar="METRES",
        help="shared obstacle inflation radius (default: 0)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    scenario = load_scenario(args.scenario)
    metadata = load_occupancy_map(scenario.map_path)
    grid = inflate_obstacles(metadata.grid, args.inflation_radius)

    results = []
    for planner in (DijkstraPlanner(), AStarPlanner(), _baseline_hybrid_astar()):
        result = planner.plan(
            grid,
            scenario.start,
            scenario.goal,
            timeout_s=scenario.timeout_s,
        )
        results.append((planner.name, result))

    print(f"scenario={scenario.name} map={metadata.image_path.name}")
    print(f"inflation_radius_m={args.inflation_radius:g}")
    print("planner       status    cost_m    poses  expanded  time_ms")
    print("------------- -------- --------- ------- --------- --------")
    for name, result in results:
        cost = "-" if result.path is None else f"{result.path.cost:.6f}"
        poses = "-" if result.path is None else str(len(result.path.poses))
        print(
            f"{name:<13} {result.status.value:<8} {cost:>9} {poses:>7} "
            f"{result.expanded_nodes:>9} {result.planning_time_s * 1000:>8.3f}"
        )

    dijkstra_result = results[0][1]
    astar_result = results[1][1]
    if dijkstra_result.path is not None and astar_result.path is not None:
        costs_match = abs(dijkstra_result.path.cost - astar_result.path.cost) <= 1e-9
        reduction = dijkstra_result.expanded_nodes - astar_result.expanded_nodes
        percentage = (
            100.0 * reduction / dijkstra_result.expanded_nodes
            if dijkstra_result.expanded_nodes
            else 0.0
        )
        print(f"optimal_cost_match={str(costs_match).lower()}")
        print(f"astar_expanded_reduction={reduction} ({percentage:.1f}%)")

    print("note=development comparison; not an official benchmark")
    return 0 if all(result.path is not None for _, result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
