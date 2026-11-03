"""Paired planner × simulation-seed experiments with separate artifacts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
from collections.abc import Mapping, Sequence
from dataclasses import asdict, fields, is_dataclass
from math import isfinite
from pathlib import Path

import numpy as np

from raceplan.common import (
    OccupancyGrid, PlannerResult, inflate_obstacles, load_occupancy_map, load_scenario,
)
from raceplan.defaults import (
    baseline_hybrid_astar, baseline_simulation_config,
    baseline_tracker_config, baseline_vehicle,
)
from raceplan.planners import AStarPlanner, DijkstraPlanner
from raceplan.planners.custom import load_custom_planner
from raceplan.simulator import NoiseConfig, run_episode

PLANNER_FACTORIES = {
    "dijkstra": DijkstraPlanner,
    "astar": AStarPlanner,
    "hybrid_astar": baseline_hybrid_astar,
}
FIELDS = (
    "episode_id", "plan_id", "scenario", "map_seed", "simulation_seed", "planner",
    "planning_status", "path_cost_m", "expanded_nodes", "planning_time_ms",
    "simulation_status", "reached", "collision", "completion_time_s",
    "goal_distance_m", "tracking_rmse_m", "max_tracking_error_m",
    "steering_total_variation_rad", "steering_saturation_fraction",
)
TRAJECTORY_FIELDS = (
    "episode_id", "step", "time_s", "x_m", "y_m", "yaw_rad", "speed_mps",
    "acceleration_mps2", "steering_angle_rad", "tracking_error_m",
)
PATH_FIELDS = ("plan_id", "waypoint", "x_m", "y_m", "yaw_rad")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/raw/development.csv"))
    parser.add_argument("--inflation-radius", type=float, default=0.0)
    parser.add_argument("--planners", nargs="+", choices=tuple(PLANNER_FACTORIES),
                        default=list(PLANNER_FACTORIES))
    parser.add_argument("--custom-planner", action="append", default=[], metavar="FILE.py:CLASS",
                        help="load a trusted custom Planner; can be specified multiple times")
    parser.add_argument("--simulation-seeds", nargs="+", type=int,
                        help="Unique non-negative seeds; defaults to the scenario seed")
    for field in fields(NoiseConfig):
        parser.add_argument("--" + field.name.replace("_", "-"), type=float, default=0.0)
    return parser


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _writer(stream, columns):
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    return writer


def _json_config(value, location: str, ancestors: frozenset[int] = frozenset()):
    """Snapshot JSON-compatible settings without silently dropping configuration."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f'{location}: configuration numbers must be finite')
        return float(value)
    if id(value) in ancestors:
        raise ValueError(f'{location}: circular configuration is not supported')
    ancestors = ancestors | {id(value)}
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: _json_config(getattr(value, field.name), f'{location}.{field.name}', ancestors)
                for field in fields(value)}
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f'{location}: configuration mapping keys must be strings')
        return {key: _json_config(item, f'{location}[{key!r}]', ancestors)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_config(item, f'{location}[{index}]', ancestors)
                for index, item in enumerate(value)]
    raise ValueError(f'{location}: unsupported configuration type {type(value).__name__}; '
                     'convert it to JSON-compatible values')


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    scenario = load_scenario(args.scenario)
    seeds = args.simulation_seeds if args.simulation_seeds is not None else [scenario.simulation_seed]
    if any(seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
        parser.error("simulation seeds must be unique non-negative integers")
    if len(set(args.planners)) != len(args.planners):
        parser.error("planner names must be unique")
    noise = NoiseConfig(**{field.name: getattr(args, field.name) for field in fields(NoiseConfig)})
    metadata = load_occupancy_map(scenario.map_path)
    grid = inflate_obstacles(metadata.grid, args.inflation_radius)
    vehicle = baseline_vehicle()
    tracker_config = baseline_tracker_config()
    simulation_config = baseline_simulation_config()
    planners = [PLANNER_FACTORIES[name]() for name in args.planners]
    custom_sources = {}
    for spec in args.custom_planner:
        try:
            custom, source = load_custom_planner(spec)
        except (ValueError, TypeError, OSError) as exc:
            parser.error(str(exc))
        if custom.name in {planner.name for planner in planners}:
            parser.error(f'duplicate planner name: {custom.name}')
        planners.append(custom)
        custom_sources[custom.name] = source
    output = args.output.resolve()
    trajectory_output = output.with_name(output.stem + "_trajectory.csv")
    path_output = output.with_name(output.stem + "_paths.csv")
    manifest_output = output.with_name(output.stem + "_manifest.json")
    outputs = (output, trajectory_output, path_output, manifest_output)
    if len(set(outputs)) != len(outputs):
        parser.error("output paths must be distinct")
    if any(path.exists() for path in outputs):
        parser.error("output artifacts already exist; choose a new --output filename")
    try:
        planner_metadata = {planner.name: {
            "class": f"{type(planner).__module__}.{type(planner).__qualname__}",
            "config": _json_config(getattr(planner, "config", {}), f'planner {planner.name!r} config'),
        } for planner in planners}
    except (ValueError, RecursionError) as exc:
        parser.error(f'invalid planner configuration: {exc}')
    manifest = {
        "schema_version": 1,
        "status": "running",
        "scenario": {**asdict(scenario), "map_path": str(scenario.map_path)},
        "scenario_file": str(args.scenario.resolve()),
        "scenario_sha256": _sha256(args.scenario),
        "map_yaml_sha256": _sha256(metadata.yaml_path),
        "map_image": str(metadata.image_path),
        "map_image_sha256": _sha256(metadata.image_path),
        "map_source": metadata.source,
        "map_license": metadata.license,
        "map_seed_semantics": "provenance only for loaded maps; no map generation",
        "simulation_seeds": seeds,
        "noise": asdict(noise),
        "noise_model": "independent Gaussian; PCG64 SeedSequence.spawn(initial, steering, speed)",
        "vehicle": asdict(vehicle),
        "tracker": asdict(tracker_config),
        "simulation": asdict(simulation_config),
        "inflation_radius_m": args.inflation_radius,
        "collision_grid": "shared inflated grid for planning and simulation",
        "planners": planner_metadata,
        "custom_planner_sources": custom_sources,
        "planning_repetitions": 1,
        "planning_note": "One plan per planner reused across seeds; times are not independent repeats",
        "planning_time_note": "planning_time_ms is planner-reported planning_time_s * 1000; the runner does not measure wall time",
        "path_cost_note": "path_cost_m is a legacy column name; cost units are planner-defined, not necessarily metres",
        "python": platform.python_version(),
        "numpy": np.__version__,
        "platform": platform.platform(),
        "source_sha256": {
            str(path.relative_to(Path(__file__).parent)): _sha256(path)
            for path in sorted(Path(__file__).parent.rglob("*.py"))
        },
        "artifacts": {"summary": output.name, "trajectory": trajectory_output.name,
                      "paths": path_output.name},
    }
    # Finish serialization before opening any artifact: invalid settings must not
    # leave an empty manifest or a result directory behind.
    try:
        manifest_json = json.dumps(manifest, indent=2, allow_nan=False)
    except (TypeError, ValueError) as exc:
        parser.error(f'manifest is not JSON-compatible: {exc}')
    output.parent.mkdir(parents=True, exist_ok=True)
    with manifest_output.open("x", encoding="utf-8") as stream:
        stream.write(manifest_json)
    with output.open("x", newline="", encoding="utf-8") as summary_stream, \
            trajectory_output.open("x", newline="", encoding="utf-8") as trajectory_stream, \
            path_output.open("x", newline="", encoding="utf-8") as path_stream:
        summary_writer = _writer(summary_stream, FIELDS)
        trajectory_writer = _writer(trajectory_stream, TRAJECTORY_FIELDS)
        path_writer = _writer(path_stream, PATH_FIELDS)
        for planner in planners:
            # A plugin can make its numpy array writable; keep simulation and other
            # planners independent even when an implementation edits its input.
            planning_grid = OccupancyGrid(grid.occupied, grid.resolution, grid.origin_x, grid.origin_y)
            planned = planner.plan(planning_grid, scenario.start, scenario.goal, timeout_s=scenario.timeout_s)
            if not isinstance(planned, PlannerResult):
                raise TypeError(f'{planner.name}.plan must return raceplan.common.PlannerResult')
            plan_id = planner.name
            if planned.path is not None:
                for index, pose in enumerate(planned.path.poses):
                    path_writer.writerow(dict(zip(PATH_FIELDS, (plan_id, index, pose.x, pose.y, pose.yaw))))
            for seed in seeds:
                episode_id = f"{plan_id}:{seed}"
                row = dict.fromkeys(FIELDS, "")
                row.update(
                    episode_id=episode_id, plan_id=plan_id, scenario=scenario.name,
                    map_seed=scenario.map_seed, simulation_seed=seed, planner=planner.name,
                    planning_status=planned.status.value,
                    path_cost_m="" if planned.path is None else planned.path.cost,
                    expanded_nodes=planned.expanded_nodes,
                    planning_time_ms=planned.planning_time_s * 1000.0,
                    simulation_status="not_run", reached=False, collision=False,
                )
                if planned.path is not None:
                    simulation = run_episode(
                        grid, planned.path, scenario.goal, vehicle, tracker_config, simulation_config,
                        initial_pose=scenario.start, simulation_seed=seed, noise=noise,
                    )
                    row.update(
                        simulation_status=simulation.status.value,
                        reached=simulation.reached, collision=simulation.collided,
                        completion_time_s=simulation.completion_time_s,
                        goal_distance_m=simulation.goal_distance,
                        tracking_rmse_m=simulation.tracking_rmse,
                        max_tracking_error_m=simulation.max_tracking_error,
                        steering_total_variation_rad=simulation.steering_total_variation,
                        steering_saturation_fraction=simulation.steering_saturation_fraction,
                    )
                    for step, sample in enumerate(simulation.samples):
                        pose = sample.state.pose
                        trajectory_writer.writerow(dict(zip(TRAJECTORY_FIELDS, (
                            episode_id, step, sample.time_s, pose.x, pose.y, pose.yaw,
                            sample.state.speed, sample.acceleration, sample.steering_angle,
                            sample.tracking_error,
                        ))))
                summary_writer.writerow(row)
                summary_stream.flush()
                trajectory_stream.flush()
                path_stream.flush()
                print(f"{episode_id}: plan={row['planning_status']} drive={row['simulation_status']}")
    manifest["status"] = "complete"
    manifest_output.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding="utf-8")
    print(f"summary={output}\ntrajectory={trajectory_output}\npaths={path_output}\nmanifest={manifest_output}")
    print("note=development settings; not an official benchmark")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
