"""Seal a new fixed split before a single validation/evaluation execution."""
from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
from time import perf_counter

import numpy as np
from PIL import Image
import yaml

from raceplan.analyze import main as analyze
from raceplan.common import OccupancyGrid, Pose2D, footprint_in_collision, load_occupancy_map
from raceplan.custom_report import main as report
from raceplan.defaults import (baseline_hybrid_astar, baseline_simulation_config,
                               baseline_tracker_config, baseline_vehicle)
from raceplan.experiment import main as experiment
from raceplan.planners.custom import load_custom_planner
from raceplan.research_design import build as historical_build, cases as historical_cases

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'examples/turn_aware_planner.py'
FAMILIES = ('staggered_windows', 'offset_islands')
SPLIT_SEEDS = {'validation': [11, 12, 13], 'evaluation': [21, 22, 23]}
PLANNERS = ['dijkstra', 'astar', 'hybrid_astar', 'turn_aware_astar', 'turn_aware_zero']
NOISE = {'initial-position-std-m': 0.02, 'initial-yaw-std-rad': 0.02,
         'steering-std-rad': 0.01, 'speed-measurement-std-mps': 0.02}
RESOLUTION = 0.2
TIMEOUT = 2.0


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    if not rows:
        return
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def grid_fingerprint(grid):
    geometry = json.dumps([grid.width, grid.height, grid.resolution, grid.origin_x, grid.origin_y])
    return sha256(geometry.encode() + grid.occupied.tobytes()).hexdigest()


def query_fingerprint(grid, start, goal):
    return sha256(json.dumps([grid_fingerprint(grid), asdict(start), asdict(goal)],
                             sort_keys=True).encode()).hexdigest()


def design(split, family):
    """New 10.4 x 7.2 m maps; no planner or simulation is run here."""
    if split not in SPLIT_SEEDS or family not in FAMILIES:
        raise ValueError('unknown split or family')
    rectangles = [(0, 0, 10.4, .2), (0, 7.0, 10.4, 7.2),
                  (0, 0, .2, 7.2), (10.2, 0, 10.4, 7.2)]
    if family == 'staggered_windows':
        if split == 'validation':
            rectangles += [(3.0, .2, 3.6, 2.0), (3.0, 4.0, 3.6, 7.0),
                           (6.6, .2, 7.2, 3.6), (6.6, 5.8, 7.2, 7.0)]
        else:
            rectangles += [(2.6, .2, 3.2, 3.0), (2.6, 5.0, 3.2, 7.0),
                           (6.2, .2, 6.8, 1.4), (6.2, 3.6, 6.8, 7.0)]
    elif split == 'validation':
        rectangles += [(3.0, 1.4, 4.6, 3.4), (5.8, 3.8, 7.4, 5.8)]
    else:
        rectangles += [(2.8, 3.6, 4.8, 5.8), (6.0, 1.2, 7.8, 3.2)]
    yy, xx = np.indices((36, 52))
    left, bottom = xx * RESOLUTION, yy * RESOLUTION
    occupied = np.zeros((36, 52), dtype=bool)
    for x0, y0, x1, y1 in rectangles:
        occupied |= ((left < x1 - 1e-9) & (left + RESOLUTION > x0 + 1e-9)
                     & (bottom < y1 - 1e-9) & (bottom + RESOLUTION > y0 + 1e-9))
    queries = [(Pose2D(1.1, 1.5, 0), Pose2D(9.3, 5.7, 0)),
               (Pose2D(1.1, 5.7, 0), Pose2D(9.3, 1.5, 0))]
    # Evaluation query coordinates are distinct too, without observing outcomes.
    if split == 'evaluation':
        queries = [(Pose2D(1.3, 1.7, 0), Pose2D(9.1, 5.5, 0)),
                   (Pose2D(1.3, 5.5, 0), Pose2D(9.1, 1.7, 0))]
    return OccupancyGrid(occupied, RESOLUTION), queries, rectangles


def historical_inventory(exclude):
    """Check both old source-generated splits and all already stored map YAMLs."""
    maps, queries, files = {}, {}, {}
    for split in ('validation', 'evaluation'):
        for case in historical_cases(split):
            grid, start, goal, _ = historical_build(case)
            maps[f'old_research_design:{case.name}'] = grid_fingerprint(grid)
            queries[f'old_research_design:{case.name}'] = query_fingerprint(grid, start, goal)
    for base in (ROOT / 'maps', ROOT / 'scenarios', ROOT / 'results/raw'):
        for path in sorted(base.rglob('*.yaml')):
            if path.resolve().is_relative_to(exclude):
                continue
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or 'image' not in data:
                continue
            metadata = load_occupancy_map(path)
            maps[str(path.relative_to(ROOT))] = grid_fingerprint(metadata.grid)
            files[str(path.resolve())] = digest(path)
            files[str(metadata.image_path)] = digest(metadata.image_path)
    return {'map_fingerprints': maps, 'query_fingerprints': queries, 'input_sha256': files}


def prepare(folder):
    if folder.exists():
        raise ValueError('run directory already exists; choose a new directory')
    history = historical_inventory(folder)
    maps, members, query_hashes = {}, [], set()
    prepared = []
    for split in SPLIT_SEEDS:
        for family in FAMILIES:
            grid, queries, rectangles = design(split, family)
            fingerprint = grid_fingerprint(grid)
            if fingerprint in maps.values() or fingerprint in history['map_fingerprints'].values():
                raise ValueError('map duplicates another split or previously used map')
            maps[f'{split}/{family}'] = fingerprint
            for index, (start, goal) in enumerate(queries):
                if any(footprint_in_collision(grid, pose, baseline_vehicle()) for pose in (start, goal)):
                    raise ValueError('query footprint is invalid')
                query_hash = query_fingerprint(grid, start, goal)
                if query_hash in query_hashes or query_hash in history['query_fingerprints'].values():
                    raise ValueError('duplicate query')
                query_hashes.add(query_hash)
                members.append({'split': split, 'family': family, 'query': index,
                                'scenario': f'inputs/{split}/{family}/q{index}.yaml',
                                'map_fingerprint': fingerprint, 'query_fingerprint': query_hash})
            prepared.append((split, family, grid, queries, rectangles))
    # Verify the frozen candidate before creating files.
    candidate, _ = load_custom_planner(f'{PLUGIN}:TurnAwareAStar')
    ablation, _ = load_custom_planner(f'{PLUGIN}:LengthOnlyAStar')
    if candidate.config.turn_weight_m_per_rad != .20 or ablation.config.turn_weight_m_per_rad != 0:
        raise ValueError('candidate weights differ from the fixed protocol')
    folder.mkdir(parents=True, exist_ok=False)
    copyfile(ROOT / 'docs/TURN_AWARE_HOLDOUT.md', folder / 'design_snapshot.md')
    for split, family, grid, queries, rectangles in prepared:
        member_folder = folder / 'inputs' / split / family
        member_folder.mkdir(parents=True, exist_ok=False)
        Image.fromarray(np.flipud(np.where(grid.occupied, 0, 255)).astype('uint8')).save(member_folder / 'map.pgm')
        with (member_folder / 'map.yaml').open('x', encoding='utf-8') as stream:
            yaml.safe_dump({'image': 'map.pgm', 'resolution': RESOLUTION, 'origin': [0., 0., 0.],
                            'source': 'RacePlan turn-aware sealed split 2026-11-03', 'license': 'CC0-1.0'}, stream)
        write_json(member_folder / 'geometry.json', {'rectangles_m': rectangles})
        for query, (start, goal) in enumerate(queries):
            with (member_folder / f'q{query}.yaml').open('x', encoding='utf-8') as stream:
                yaml.safe_dump({'name': f'{split}_{family}_q{query}', 'map': 'map.yaml',
                                'start': [start.x, start.y, start.yaw], 'goal': [goal.x, goal.y, goal.yaw],
                                'map_seed': None, 'simulation_seed': SPLIT_SEEDS[split][0],
                                'timeout_s': TIMEOUT}, stream)
    write_json(folder / 'novelty.json', history | {'new_map_fingerprints': maps,
                                                 'exact_map_overlap_count': 0, 'exact_query_overlap_count': 0})
    sources = sorted((ROOT / 'src/raceplan').rglob('*.py')) + [PLUGIN, Path(__file__).resolve()]
    protocol = {'version': 1, 'suite': 'turn_aware_holdout_20261103', 'members': members,
                'split_seeds': SPLIT_SEEDS, 'planners': PLANNERS, 'noise': NOISE,
                'turn_weight_m_per_rad': .20, 'ablation_weight': 0,
                'planning_timeout_s': TIMEOUT, 'planning_calls_per_query_planner': 1,
                'episodes': 120, 'maps_per_split': 2, 'queries_per_map': 2,
                'inflation_radius_m': 0., 'collision_grid': 'original physical grid for every planner and simulator',
                'planning_representation_limit': 'grid point vs Hybrid rotated footprint; not equivalent',
                'vehicle': asdict(baseline_vehicle()), 'tracker': asdict(baseline_tracker_config()),
                'simulation': asdict(baseline_simulation_config()),
                'hybrid': asdict(baseline_hybrid_astar().config),
                'success': 'collision-free position within 0.5 m; yaw descriptive',
                'execution_policy': 'validation once then evaluation once; no selection or tuning; no resume',
                'worst_policy': 'all failures plus top 3 reached by RMSE and lowest 3 driving clearances per split/planner',
                'timing_policy': '4 once-reported plans per split/planner; seed duplicates removed; no speed inference',
                'source_sha256': {str(path): digest(path) for path in sources},
                'input_sha256': {str(path.relative_to(folder)): digest(path)
                                 for path in sorted(folder.rglob('*')) if path.is_file()}}
    write_json(folder / 'protocol.json', protocol)
    write_json(folder / 'seal.json', {'protocol_sha256': digest(folder / 'protocol.json'),
                                     'design_snapshot_sha256': digest(folder / 'design_snapshot.md')})
    return protocol


def verify_seal(folder):
    seal = json.loads((folder / 'seal.json').read_text(encoding='utf-8'))
    if digest(folder / 'protocol.json') != seal['protocol_sha256']:
        raise ValueError('protocol seal mismatch')
    protocol = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))
    for path, expected in protocol['source_sha256'].items():
        if digest(Path(path)) != expected:
            raise ValueError(f'source seal mismatch: {path}')
    for name, expected in protocol['input_sha256'].items():
        if digest(folder / name) != expected:
            raise ValueError(f'input seal mismatch: {name}')
    return protocol


def aggregate(folder, split, episodes, plans, paired):
    aggregates, effects, worst, families = [], [], [], []
    for planner in PLANNERS:
        rows = [r for r in episodes if r['planner'] == planner]
        succeeded = [r for r in rows if r['failure_class'] == 'reached']
        failures = [r for r in rows if r['failure_class'] != 'reached']
        driven = [r for r in rows if r['driving_min_sampled_clearance_m'] != '']
        measured = [r for r in plans if r['planner'] == planner]
        summary = {'split': split, 'planner': planner, 'episodes': len(rows), 'reached': len(succeeded),
                   'collisions': sum(r['collision'] == 'True' for r in rows),
                   'timeouts': sum(r['simulation_status'] == 'timeout' for r in rows),
                   'planning_failures': sum(r['planning_status'] != 'success' for r in rows),
                   'planning_calls': len(measured)}
        for metric in ('tracking_rmse_m', 'completion_time_s'):
            summary[f'success_median_{metric}'] = float(np.median([float(r[metric]) for r in succeeded])) if succeeded else None
        summary['all_driven_min_clearance_m'] = min(float(r['driving_min_sampled_clearance_m']) for r in driven) if driven else None
        for metric in ('planning_time_ms', 'expanded_nodes'):
            values = [float(r[metric]) for r in measured]
            summary[f'{metric}_median'] = float(np.median(values))
            summary[f'{metric}_p95'] = float(np.quantile(values, .95))
        aggregates.append(summary)
        for criterion, selected in (
            ('failure', failures),
            ('highest_reached_rmse', sorted(succeeded, key=lambda r: float(r['tracking_rmse_m']), reverse=True)[:3]),
            ('lowest_driving_clearance', sorted(driven, key=lambda r: float(r['driving_min_sampled_clearance_m']))[:3]),
        ):
            worst += [{'criterion': criterion, **r} for r in selected]
        pairs = [r for r in paired if r['planner'] == planner]
        if pairs:
            effect = {'split': split, 'planner': planner, 'baseline': 'astar', 'pairs': len(pairs),
                      'reach_wins': sum(r['planner_outcome'] == 'reached' and r['baseline_outcome'] != 'reached' for r in pairs),
                      'reach_losses': sum(r['planner_outcome'] != 'reached' and r['baseline_outcome'] == 'reached' for r in pairs),
                      'both_reached': sum(r['both_reached'] == 'True' for r in pairs)}
            for metric in ('delta_tracking_rmse_m', 'delta_completion_time_s', 'delta_driving_min_sampled_clearance_m'):
                values = [float(r[metric]) for r in pairs if r[metric] != '']
                effect[f'{metric}_median'] = float(np.median(values)) if values else None
                effect[f'{metric}_pairs'] = len(values)
            effect['reach_rate_delta'] = (effect['reach_wins'] - effect['reach_losses']) / len(pairs)
            effects.append(effect)
        for family in FAMILIES:
            group = [r for r in rows if r['family'] == family]
            families.append({'split': split, 'family': family, 'planner': planner, 'episodes': len(group),
                             'reached': sum(r['failure_class'] == 'reached' for r in group),
                             'collisions': sum(r['collision'] == 'True' for r in group),
                             'timeouts': sum(r['simulation_status'] == 'timeout' for r in group),
                             'planning_failures': sum(r['planning_status'] != 'success' for r in group)})
    write_csv(folder / f'{split}_episodes.csv', episodes)
    write_csv(folder / f'{split}_planning.csv', plans)
    write_csv(folder / f'{split}_paired.csv', paired)
    write_csv(folder / f'{split}_summary.csv', aggregates)
    write_csv(folder / f'{split}_effects.csv', effects)
    write_csv(folder / f'{split}_worst.csv', worst)
    write_csv(folder / f'{split}_families.csv', families)
    return {'outcomes': aggregates, 'paired_effects': effects}


def execute(folder):
    protocol = verify_seal(folder)
    # Exclusive claim precedes all planning; an interrupted run is never silently repeated.
    write_json(folder / 'execution_started.json', {'seal_sha256': digest(folder / 'seal.json')})
    started, result = perf_counter(), {}
    for split in SPLIT_SEEDS:
        split_start = perf_counter()
        episodes, plans, pairs = [], [], []
        for member in [m for m in protocol['members'] if m['split'] == split]:
            verify_seal(folder)
            case = f'{split}_{member["family"]}_q{member["query"]}'
            target = folder / 'batches' / case
            summary = target / 'comparison.csv'
            command = [str(folder / member['scenario']), '--output', str(summary),
                       '--simulation-seeds', *map(str, protocol['split_seeds'][split]),
                       '--custom-planner', f'{PLUGIN}:TurnAwareAStar',
                       '--custom-planner', f'{PLUGIN}:LengthOnlyAStar']
            for setting, value in protocol['noise'].items():
                command += ['--' + setting, str(value)]
            experiment(command)
            analyze([str(summary), '--baseline', 'astar', '--output-dir', str(target / 'analysis')])
            report([str(summary), '--output', str(target / 'comparison.png')])
            dimensions = {'split': split, 'family': member['family'], 'query': member['query'], 'case': case}
            local = read_csv(target / 'analysis/episodes.csv')
            episodes += [dimensions | r for r in local]
            pairs += [dimensions | r for r in read_csv(target / 'analysis/paired.csv')]
            seen = set()
            for row in local:
                if row['planner'] in seen:
                    continue
                seen.add(row['planner'])
                plans.append(dimensions | {key: row[key] for key in (
                    'planner', 'planning_status', 'planning_time_ms', 'expanded_nodes', 'path_cost_m',
                    'path_length_m', 'total_absolute_turn_rad', 'max_discrete_curvature_per_m')})
            verify_seal(folder)
        result[split] = aggregate(folder, split, episodes, plans, pairs)
        result[split]['wall_time_s'] = perf_counter() - split_start
    verify_seal(folder)
    result['total_wall_time_s'] = perf_counter() - started
    write_json(folder / 'summary.json', result)
    write_json(folder / 'complete.json', {
        'seal_sha256': digest(folder / 'seal.json'), 'status': 'complete',
        'artifact_sha256': {str(path.relative_to(folder)): digest(path)
                            for path in sorted(folder.rglob('*')) if path.is_file()},
    })
    print(f'completed sealed validation/evaluation -> {folder}', flush=True)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--execute-sealed', action='store_true')
    args = parser.parse_args(argv)
    if args.prepare_only and args.execute_sealed:
        parser.error('choose only one phase')
    folder = args.output_dir.resolve()
    if not args.execute_sealed:
        prepare(folder)
    if not args.prepare_only:
        execute(folder)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
