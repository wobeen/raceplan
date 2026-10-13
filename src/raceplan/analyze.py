"""Analyze one saved batch without replanning, rerunning, or pooling conditions."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from raceplan.common import Pose2D, VehicleGeometry, inflate_obstacles, load_occupancy_map
from raceplan.metrics import Clearance, path_metrics, trajectory_clearance


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def _write(path, rows):
    if not rows:
        return
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def failure_class(row):
    if row['planning_status'] != 'success':
        return 'planning_' + row['planning_status']
    status = row['simulation_status']
    if status == 'collision':
        return 'initial_collision' if float(row['completion_time_s']) == 0 else 'driving_collision'
    if status in {'timeout', 'reached'}:
        return status
    raise ValueError(f"unexpected simulation status: {status}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--spacing', type=float, default=0.1)
    parser.add_argument('--baseline', default='dijkstra')
    args = parser.parse_args(argv)
    if not np.isfinite(args.spacing) or args.spacing <= 0:
        parser.error('spacing must be finite and positive')
    if args.output_dir.exists():
        parser.error('output directory already exists; select a new directory')
    summary = args.summary.resolve()
    manifest_path = summary.with_name(summary.stem + '_manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('status') != 'complete':
        raise ValueError('a completed schema-version 1 batch is required')
    if manifest['artifacts']['summary'] != summary.name:
        raise ValueError('summary does not match its manifest')
    path_name = manifest['artifacts']['paths']
    if Path(path_name).name != path_name:
        raise ValueError('path artifact must be a sibling filename')
    path_file = summary.with_name(path_name)
    trajectory_name = manifest['artifacts']['trajectory']
    if Path(trajectory_name).name != trajectory_name:
        raise ValueError('trajectory artifact must be a sibling filename')
    trajectory_file = summary.with_name(trajectory_name)
    map_path = Path(manifest['scenario']['map_path'])
    if _hash(map_path) != manifest['map_yaml_sha256']:
        raise ValueError('map YAML changed since the batch')
    metadata = load_occupancy_map(map_path)
    if _hash(metadata.image_path) != manifest['map_image_sha256']:
        raise ValueError('map image changed since the batch')
    raw_grid = metadata.grid
    grid = inflate_obstacles(raw_grid, manifest['inflation_radius_m'])
    vehicle = VehicleGeometry(**manifest['vehicle'])
    start = Pose2D(**manifest['scenario']['start'])
    goal = Pose2D(**manifest['scenario']['goal'])
    paths = defaultdict(list)
    for row in _read(path_file):
        paths[row['plan_id']].append((int(row['waypoint']), Pose2D(
            float(row['x_m']), float(row['y_m']), float(row['yaw_rad']))))
    plan_metrics = {}
    for plan_id, waypoints in paths.items():
        waypoints.sort(key=lambda item: item[0])
        if [index for index, _ in waypoints] != list(range(len(waypoints))):
            raise ValueError('waypoint indices must be unique and contiguous')
        plan_metrics[plan_id] = path_metrics(tuple(pose for _, pose in waypoints),
                                             grid, vehicle, start, goal, args.spacing)
    metric_names = (
        'path_length_m', 'path_to_query_distance_ratio', 'path_start_offset_m',
        'path_goal_offset_m', 'path_goal_yaw_error_rad', 'sample_spacing_m', 'sample_count',
        'total_absolute_turn_rad', 'max_discrete_curvature_per_m',
        'min_sampled_footprint_clearance_m', 'min_sampled_footprint_clearance_vehicle_widths',
        'min_sampled_reference_clearance_m', 'local_clearance_diameter_proxy_vehicle_widths',
    )
    episodes = _read(summary)
    if not episodes:
        raise ValueError('empty batch')
    seen_ids, seen_pairs = set(), set()
    for row in episodes:
        pair = (row['planner'], int(row['simulation_seed']))
        if row['episode_id'] in seen_ids or pair in seen_pairs:
            raise ValueError('duplicate episode or planner/seed pair')
        seen_ids.add(row['episode_id'])
        seen_pairs.add(pair)
        if row['planning_status'] == 'success' and row['plan_id'] not in plan_metrics:
            raise ValueError('successful plan has no saved waypoints')
        row.update({name: None for name in metric_names})
        row.update(plan_metrics.get(row['plan_id'], {}))
        row['failure_class'] = failure_class(row)
        row['raw_obstacle_density'] = float(raw_grid.occupied.mean())
        row['inflated_obstacle_density'] = float(grid.occupied.mean())
        row['tracking_rmse_vehicle_widths'] = (
            float(row['tracking_rmse_m']) / vehicle.width if row['tracking_rmse_m'] else None)
    expected = {(planner, seed) for planner in manifest['planners'] for seed in manifest['simulation_seeds']}
    if seen_pairs != expected:
        raise ValueError('episode planner/seed coverage does not match manifest')
    trajectories = defaultdict(list)
    for sample in _read(trajectory_file):
        if sample['episode_id'] not in seen_ids:
            raise ValueError('trajectory references an unknown episode')
        trajectories[sample['episode_id']].append(sample)
    clearance = Clearance(grid)
    clearance_samples = []
    for row in episodes:
        row.update(driving_min_sampled_clearance_m=None,
                   driving_min_sampled_clearance_vehicle_widths=None,
                   driving_min_clearance_time_s=None,
                   driving_minus_plan_min_clearance_m=None)
        samples = trajectories.get(row['episode_id'], [])
        if row['planning_status'] != 'success':
            if samples:
                raise ValueError('failed planning episode has a trajectory')
            continue
        if not samples:
            raise ValueError('driven episode has no trajectory')
        samples.sort(key=lambda sample: int(sample['step']))
        if [int(s['step']) for s in samples] != list(range(len(samples))):
            raise ValueError('trajectory steps must be unique and contiguous')
        times = [float(s['time_s']) for s in samples]
        if (not all(np.isfinite(t) for t in times) or times[0] != 0.0
                or any(b <= a for a, b in zip(times, times[1:]))
                or not np.isclose(times[-1], float(row['completion_time_s']), rtol=0, atol=1e-8)
                or not np.allclose(times, np.arange(len(times)) * manifest['simulation']['dt'],
                                   rtol=0, atol=1e-8)):
            raise ValueError('trajectory times do not match episode duration and simulation step')
        poses = tuple(Pose2D(float(s['x_m']), float(s['y_m']), float(s['yaw_rad'])) for s in samples)
        values = trajectory_clearance(poses, clearance, vehicle)
        minimum_index = min(range(len(values)), key=values.__getitem__)
        minimum = values[minimum_index]
        row.update(driving_min_sampled_clearance_m=minimum,
                   driving_min_sampled_clearance_vehicle_widths=minimum / vehicle.width,
                   driving_min_clearance_time_s=times[minimum_index],
                   driving_minus_plan_min_clearance_m=minimum - row['min_sampled_footprint_clearance_m'])
        for sample, value in zip(samples, values):
            clearance_samples.append({key: sample[key] for key in
                                      ('episode_id', 'step', 'time_s', 'x_m', 'y_m', 'yaw_rad')}
                                     | {'footprint_clearance_m': value})
    groups = defaultdict(list)
    for row in episodes:
        groups[row['planner']].append(row)
    if args.baseline not in groups:
        raise ValueError('baseline planner is absent from this batch')
    aggregates = []
    for planner, rows in groups.items():
        counts = Counter(row['failure_class'] for row in rows)
        successes = [row for row in rows if row['failure_class'] == 'reached']
        aggregate = dict(planner=planner, episodes=len(rows), reached=len(successes),
                         reach_rate=len(successes) / len(rows),
                         planning_failures=sum(v for k, v in counts.items() if k.startswith('planning_')),
                         initial_collisions=counts['initial_collision'],
                         driving_collisions=counts['driving_collision'], timeouts=counts['timeout'])
        for metric in ('tracking_rmse_m', 'completion_time_s', 'steering_saturation_fraction'):
            values = [float(row[metric]) for row in successes]
            for name, quantile in [('median', 0.5), ('q25', 0.25), ('q75', 0.75), ('q90', 0.9)]:
                aggregate[f'success_{metric}_{name}'] = float(np.quantile(values, quantile)) if values else None
        aggregates.append(aggregate)
        driving_values = [row['driving_min_sampled_clearance_m'] for row in rows
                          if row['driving_min_sampled_clearance_m'] is not None]
        aggregate['driven_episodes'] = len(driving_values)
        for label, q in [('min', 0.0), ('q10', 0.1), ('median', 0.5)]:
            aggregate[f'all_driven_min_clearance_m_{label}'] = (
                float(np.quantile(driving_values, q)) if driving_values else None)
    baseline = {row['simulation_seed']: row for row in groups[args.baseline]}
    pairs = []
    for row in episodes:
        if row['planner'] == args.baseline:
            continue
        reference = baseline[row['simulation_seed']]
        both_reached = row['failure_class'] == reference['failure_class'] == 'reached'
        pair = dict(planner=row['planner'], baseline=args.baseline,
                    simulation_seed=row['simulation_seed'],
                    planner_outcome=row['failure_class'], baseline_outcome=reference['failure_class'],
                    both_reached=both_reached)
        for metric in ('tracking_rmse_m', 'completion_time_s', 'steering_saturation_fraction'):
            pair['delta_' + metric] = float(row[metric]) - float(reference[metric]) if both_reached else None
        both_driven = all(r['driving_min_sampled_clearance_m'] is not None for r in (row, reference))
        pair['both_driven'] = both_driven
        pair['delta_driving_min_sampled_clearance_m'] = (
            row['driving_min_sampled_clearance_m'] - reference['driving_min_sampled_clearance_m']
            if both_driven else None)
        pairs.append(pair)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    _write(args.output_dir / 'episodes.csv', episodes)
    _write(args.output_dir / 'planners.csv', aggregates)
    _write(args.output_dir / 'paired.csv', pairs)
    _write(args.output_dir / 'clearance_samples.csv', clearance_samples)
    provenance = {
        'analysis_schema_version': 2, 'summary': str(summary),
        'input_sha256': {str(path): _hash(path) for path in (summary, manifest_path, path_file, trajectory_file)},
        'source_sha256': {name: _hash(Path(__file__).with_name(name)) for name in ('analyze.py', 'metrics.py')},
        'numpy': np.__version__, 'requested_spacing_m': args.spacing, 'baseline': args.baseline,
        'clearance_grid': 'inflated grid, matching batch planning and driving',
        'curvature': 'absolute change in resampled XY segment heading / arc-length spacing',
        'clearance': 'minimum sampled footprint distance; zero for overlap or contact; not swept clearance',
        'diameter_proxy': 'twice minimum reference-point clearance / width; NOT map bottleneck width',
        'aggregation': 'one batch only; all failures counted; continuous quantiles on reached episodes only',
        'pair_delta': 'planner minus baseline, continuous metrics only when both reached',
        'driving_clearance': 'all recorded true poses including failures; no temporal resampling or swept guarantee',
        'driving_clearance_aggregation': 'all driven episodes including collision and timeout; lower tail q10',
        'driving_clearance_pair_delta': 'planner minus baseline when both drove, including failures',
        'plan_comparison_limit': 'different sampling, endpoint coverage and yaw; delta is descriptive, not pointwise loss',
    }
    (args.output_dir / 'analysis.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print(f'analyzed {len(episodes)} episodes -> {args.output_dir.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
