"""Run the complete planner-to-controller development experiment."""

from __future__ import annotations

import argparse
import csv
from collections.abc import Sequence
from pathlib import Path

from raceplan.common import inflate_obstacles, load_occupancy_map, load_scenario
from raceplan.defaults import (
    baseline_hybrid_astar,
    baseline_simulation_config,
    baseline_tracker_config,
    baseline_vehicle,
)
from raceplan.planners import AStarPlanner, DijkstraPlanner
from raceplan.simulator import run_episode


FIELDS = (
    "scenario",
    "seed",
    "planner",
    "planning_status",
    "path_cost_m",
    "expanded_nodes",
    "planning_time_ms",
    "simulation_status",
    "reached",
    "collision",
    "completion_time_s",
    "goal_distance_m",
    "tracking_rmse_m",
    "max_tracking_error_m",
    "steering_total_variation_rad",
    "steering_saturation_fraction",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan and track one scenario with all baseline planners.",
    )
    parser.add_argument("scenario", type=Path, help="scenario YAML path")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/raw/development.csv"),
        help="output CSV path",
    )
    parser.add_argument(
        "--inflation-radius",
        type=float,
        default=0.0,
        metavar="METRES",
        help="shared obstacle inflation radius",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    scenario = load_scenario(args.scenario)
    metadata = load_occupancy_map(scenario.map_path)
    grid = inflate_obstacles(metadata.grid, args.inflation_radius)
    vehicle = baseline_vehicle()
    tracker_config = baseline_tracker_config()
    simulation_config = baseline_simulation_config()
    planners = (DijkstraPlanner(), AStarPlanner(), baseline_hybrid_astar())

    rows: list[dict[str, object]] = []
    for planner in planners:
        planned = planner.plan(
            grid,
            scenario.start,
            scenario.goal,
            timeout_s=scenario.timeout_s,
        )
        row: dict[str, object] = {
            "scenario": scenario.name,
            "seed": scenario.seed,
            "planner": planner.name,
            "planning_status": planned.status.value,
            "path_cost_m": "" if planned.path is None else planned.path.cost,
            "expanded_nodes": planned.expanded_nodes,
            "planning_time_ms": planned.planning_time_s * 1000.0,
            "simulation_status": "not_run",
            "reached": False,
            "collision": False,
            "completion_time_s": "",
            "goal_distance_m": "",
            "tracking_rmse_m": "",
            "max_tracking_error_m": "",
            "steering_total_variation_rad": "",
            "steering_saturation_fraction": "",
        }
        if planned.path is not None:
            simulation = run_episode(
                grid,
                planned.path,
                scenario.goal,
                vehicle,
                tracker_config,
                simulation_config,
            )
            row.update(
                {
                    "simulation_status": simulation.status.value,
                    "reached": simulation.reached,
                    "collision": simulation.collided,
                    "completion_time_s": simulation.completion_time_s,
                    "goal_distance_m": simulation.goal_distance,
                    "tracking_rmse_m": simulation.tracking_rmse,
                    "max_tracking_error_m": simulation.max_tracking_error,
                    "steering_total_variation_rad": simulation.steering_total_variation,
                    "steering_saturation_fraction": simulation.steering_saturation_fraction,
                }
            )
        rows.append(row)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    print(f"scenario={scenario.name} seed={scenario.seed}")
    print("planner       plan       drive      reached collision rmse_m   time_s")
    print("------------- ---------- ---------- ------- -------- -------- --------")
    for row in rows:
        rmse = row["tracking_rmse_m"]
        elapsed = row["completion_time_s"]
        rmse_text = "-" if rmse == "" else f"{float(rmse):.4f}"
        elapsed_text = "-" if elapsed == "" else f"{float(elapsed):.2f}"
        print(
            f"{row['planner']:<13} {row['planning_status']:<10} "
            f"{row['simulation_status']:<10} {str(row['reached']):<7} "
            f"{str(row['collision']):<8} {rmse_text:>8} {elapsed_text:>8}"
        )
    print(f"csv={output}")
    print("note=development controller settings; not an official benchmark")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
