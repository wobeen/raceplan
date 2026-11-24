"""Seal new held-out maps, then run the fixed A* smoothing candidate exactly once.

See docs/SMOOTHING_HOLDOUT.md.  The candidate was selected on the exposed
turn-aware validation split; this split has no validation phase and no
selection or tuning branch.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from shutil import copyfile
from time import perf_counter

import numpy as np
from PIL import Image
import yaml

from raceplan.analyze import main as analyze
from raceplan.common import (OccupancyGrid, Pose2D, footprint_in_collision, load_occupancy_map,
                             load_scenario)
from raceplan.custom_report import main as report
from raceplan.defaults import (baseline_hybrid_astar, baseline_simulation_config,
                               baseline_tracker_config, baseline_vehicle)
from raceplan.experiment import main as experiment
from raceplan.planners.custom import load_custom_planner
from raceplan.research_design import build as historical_build, cases as historical_cases

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'examples/smoothed_astar_planner.py'
IDENTITY = ROOT / 'results/turn_aware_query_identity_v2.py'
DESIGN_DOC = ROOT / 'docs/SMOOTHING_HOLDOUT.md'
SUITE = 'smoothing_holdout_20261123'
FAMILIES = ('staggered_windows', 'offset_islands', 'slalom_walls')
VARIANTS = ('a', 'b')
SEEDS = [31, 32, 33]
CANDIDATE, ABLATION = 'SmoothedLowClearance', 'SmoothedNoClearance'
CANDIDATE_NAME, ABLATION_NAME = 'smoothed_low_clearance', 'smoothed_no_clearance'
PLANNERS = ['dijkstra', 'astar', 'hybrid_astar', CANDIDATE_NAME, ABLATION_NAME]
FIXED_CONFIG = {'target_clearance_m': .30, 'footprint_margin_m': .02, 'spacing_m': .1,
                'iterations': 100, 'smoothing_weight': 100., 'clearance_step': .5}
NOISE = {'initial-position-std-m': 0.02, 'initial-yaw-std-rad': 0.02,
         'steering-std-rad': 0.01, 'speed-measurement-std-mps': 0.02}
RESOLUTION = 0.2
SHAPE = (36, 52)
TIMEOUT = 2.0
QUERIES = [(Pose2D(1.2, 1.6, 0), Pose2D(9.2, 5.6, 0)),
           (Pose2D(1.2, 5.6, 0), Pose2D(9.2, 1.6, 0))]
INTERIOR = {
    ('staggered_windows', 'a'): [(3.4, .2, 4.0, 1.0), (3.4, 3.0, 4.0, 7.0),
                                 (6.8, .2, 7.4, 4.4), (6.8, 6.4, 7.4, 7.0)],
    ('staggered_windows', 'b'): [(2.8, .2, 3.4, 3.8), (2.8, 5.8, 3.4, 7.0),
                                 (6.4, .2, 7.0, 1.0), (6.4, 3.2, 7.0, 7.0)],
    ('offset_islands', 'a'): [(2.4, 1.0, 3.8, 3.0), (4.8, 3.8, 6.2, 5.8), (7.2, 1.4, 8.6, 3.4)],
    ('offset_islands', 'b'): [(2.6, 4.0, 4.0, 6.2), (5.0, 1.0, 6.4, 3.2), (7.4, 3.8, 8.8, 5.8)],
    ('slalom_walls', 'a'): [(3.4, .2, 3.8, 4.4), (6.6, 2.8, 7.0, 7.0)],
    ('slalom_walls', 'b'): [(3.0, 2.6, 3.4, 7.0), (6.8, .2, 7.2, 4.6)],
}


def load_identity():
    spec = importlib.util.spec_from_file_location('_raceplan_query_identity_v2', IDENTITY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


identity = load_identity()


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


def median_or_none(values):
    return float(np.median(values)) if values else None


def design(family, variant):
    """Fixed new 10.4 x 7.2 m map and queries; no planner or simulation is run here."""
    if (family, variant) not in INTERIOR:
        raise ValueError('unknown family or variant')
    rectangles = [(0, 0, 10.4, .2), (0, 7.0, 10.4, 7.2),
                  (0, 0, .2, 7.2), (10.2, 0, 10.4, 7.2)] + INTERIOR[family, variant]
    yy, xx = np.indices(SHAPE)
    left, bottom = xx * RESOLUTION, yy * RESOLUTION
    occupied = np.zeros(SHAPE, dtype=bool)
    for x0, y0, x1, y1 in rectangles:
        occupied |= ((left < x1 - 1e-9) & (left + RESOLUTION > x0 + 1e-9)
                     & (bottom < y1 - 1e-9) & (bottom + RESOLUTION > y0 + 1e-9))
    return OccupancyGrid(occupied, RESOLUTION), list(QUERIES), rectangles


def historical_inventory(exclude):
    """v2 identities of every previously generated or stored map and scenario query."""
    maps, queries = {}, {}
    for split in ('validation', 'evaluation'):
        for case in historical_cases(split):
            grid, start, goal, _ = historical_build(case)
            maps[f'research_design:{case.name}'] = identity.grid_fingerprint_v2(grid)
            queries[f'research_design:{case.name}'] = identity.query_fingerprint_v2(grid, start, goal)
    for base in (ROOT / 'maps', ROOT / 'scenarios', ROOT / 'results/raw', ROOT / 'results/analysis'):
        for path in sorted(base.rglob('*.yaml')):
            if path.resolve().is_relative_to(exclude):
                continue
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                continue
            name = str(path.relative_to(ROOT))
            if 'image' in data:
                maps[name] = identity.grid_fingerprint_v2(load_occupancy_map(path).grid)
            elif {'map', 'start', 'goal'} <= data.keys():
                scenario = load_scenario(path)
                grid = load_occupancy_map(scenario.map_path).grid
                queries[name] = identity.query_fingerprint_v2(grid, scenario.start, scenario.goal)
    return {'map_fingerprints_v2': maps, 'query_fingerprints_v2': queries}


def check_candidate():
    for classname, target in ((CANDIDATE, FIXED_CONFIG['target_clearance_m']), (ABLATION, 0.)):
        config = asdict(load_custom_planner(f'{PLUGIN}:{classname}')[0].config)
        expected = FIXED_CONFIG | {'target_clearance_m': target}
        if any(config[key] != value for key, value in expected.items()):
            raise ValueError(f'{classname} configuration differs from the fixed protocol')


def prepare(folder):
    if folder.exists():
        raise ValueError('run directory already exists; choose a new directory')
    check_candidate()
    history = historical_inventory(folder)
    old_maps = set(history['map_fingerprints_v2'].values())
    old_queries = set(history['query_fingerprints_v2'].values())
    new_maps, members, query_hashes, prepared = {}, [], set(), []
    for family in FAMILIES:
        for variant in VARIANTS:
            grid, queries, rectangles = design(family, variant)
            fingerprint = identity.grid_fingerprint_v2(grid)
            if fingerprint in old_maps or fingerprint in new_maps.values():
                raise ValueError('map duplicates another new map or a previously used map')
            new_maps[f'{family}/{variant}'] = fingerprint
            for start, goal in queries:
                if any(footprint_in_collision(grid, pose, baseline_vehicle()) for pose in (start, goal)):
                    raise ValueError('query footprint is invalid')
                query_hash = identity.query_fingerprint_v2(grid, start, goal)
                if query_hash in old_queries or query_hash in query_hashes:
                    raise ValueError('duplicate query')
                query_hashes.add(query_hash)
            prepared.append((family, variant, grid, queries, rectangles))

    folder.mkdir(parents=True)
    copyfile(DESIGN_DOC, folder / 'design_snapshot.md')
    for family, variant, grid, queries, rectangles in prepared:
        member_folder = folder / 'inputs' / family / variant
        member_folder.mkdir(parents=True)
        image = np.flipud(np.where(grid.occupied, 0, 255)).astype('uint8')
        Image.fromarray(image).save(member_folder / 'map.pgm')
        with (member_folder / 'map.yaml').open('x', encoding='utf-8') as stream:
            yaml.safe_dump({'image': 'map.pgm', 'resolution': RESOLUTION, 'origin': [0., 0., 0.],
                            'source': f'RacePlan sealed split {SUITE}', 'license': 'CC0-1.0'}, stream)
        write_json(member_folder / 'geometry.json', {'rectangles_m': rectangles})
        for query, (start, goal) in enumerate(queries):
            scenario = member_folder / f'q{query}.yaml'
            with scenario.open('x', encoding='utf-8') as stream:
                yaml.safe_dump({'name': f'{family}_{variant}_q{query}', 'map': 'map.yaml',
                                'start': [start.x, start.y, start.yaw],
                                'goal': [goal.x, goal.y, goal.yaw], 'map_seed': None,
                                'simulation_seed': SEEDS[0], 'timeout_s': TIMEOUT}, stream)
            members.append({
                'family': family, 'variant': variant, 'query': query,
                'scenario': str(scenario.relative_to(folder).as_posix()),
                'map_fingerprint_v2': new_maps[f'{family}/{variant}'],
                'query_fingerprint_v2': identity.validate_scenario_roundtrip(grid, start, goal, scenario),
            })
    write_json(folder / 'novelty.json', history | {
        'new_map_fingerprints_v2': new_maps,
        'exact_map_overlap_count': 0, 'exact_query_overlap_count': 0})
    sources = (sorted((ROOT / 'src/raceplan').rglob('*.py'))
               + [PLUGIN, Path(__file__).resolve(), IDENTITY])
    protocol = {
        'version': 1, 'suite': SUITE, 'members': members, 'families': list(FAMILIES),
        'seeds': SEEDS, 'planners': PLANNERS, 'candidate': CANDIDATE_NAME,
        'ablation': ABLATION_NAME, 'candidate_config': FIXED_CONFIG, 'noise': NOISE,
        'planning_timeout_s': TIMEOUT, 'planning_calls_per_query_planner': 1,
        'episodes': len(members) * len(SEEDS) * len(PLANNERS), 'inflation_radius_m': 0.,
        'vehicle': asdict(baseline_vehicle()), 'tracker': asdict(baseline_tracker_config()),
        'simulation': asdict(baseline_simulation_config()),
        'hybrid': asdict(baseline_hybrid_astar().config),
        'success': 'collision-free position within 0.5 m; yaw descriptive',
        'decision_rule': ('held-out support iff candidate reach wins > losses vs A* over all '
                          'pairs and no family has more losses than wins'),
        'execution_policy': 'single evaluation run; no validation, selection, tuning, or resume',
        'acceptance_audit': 'post-run deterministic re-plan of candidate and ablation; descriptive only',
        'source_sha256': {str(path.relative_to(ROOT).as_posix()): digest(path) for path in sources},
        'input_sha256': {str(path.relative_to(folder).as_posix()): digest(path)
                         for path in sorted(folder.rglob('*')) if path.is_file()},
    }
    write_json(folder / 'protocol.json', protocol)
    write_json(folder / 'seal.json', {'protocol_sha256': digest(folder / 'protocol.json'),
                                     'design_snapshot_sha256': digest(folder / 'design_snapshot.md')})
    return protocol


def verify_seal(folder):
    seal = json.loads((folder / 'seal.json').read_text(encoding='utf-8'))
    if digest(folder / 'protocol.json') != seal['protocol_sha256']:
        raise ValueError('protocol seal mismatch')
    if digest(folder / 'design_snapshot.md') != seal['design_snapshot_sha256']:
        raise ValueError('design snapshot seal mismatch')
    protocol = json.loads((folder / 'protocol.json').read_text(encoding='utf-8'))
    for path, expected in protocol['source_sha256'].items():
        if digest(ROOT / path) != expected:
            raise ValueError(f'source seal mismatch: {path}')
    for name, expected in protocol['input_sha256'].items():
        if digest(folder / name) != expected:
            raise ValueError(f'input seal mismatch: {name}')
    return protocol


def paired_effect(rows, **dimensions):
    effect = dimensions | {
        'pairs': len(rows),
        'reach_wins': sum(r['planner_outcome'] == 'reached' and r['baseline_outcome'] != 'reached'
                          for r in rows),
        'reach_losses': sum(r['planner_outcome'] != 'reached' and r['baseline_outcome'] == 'reached'
                            for r in rows),
        'both_reached': sum(r['both_reached'] == 'True' for r in rows)}
    for metric in ('delta_tracking_rmse_m', 'delta_completion_time_s',
                   'delta_driving_min_sampled_clearance_m'):
        values = [float(r[metric]) for r in rows if r[metric] != '']
        effect[f'{metric}_median'] = median_or_none(values)
        effect[f'{metric}_pairs'] = len(values)
    effect['reach_rate_delta'] = ((effect['reach_wins'] - effect['reach_losses']) / len(rows)
                                  if rows else None)
    return effect


def aggregate(folder, episodes, plans, paired, acceptance):
    summary, effects, worst, groups = [], [], [], []
    for planner in PLANNERS:
        rows = [r for r in episodes if r['planner'] == planner]
        reached = [r for r in rows if r['failure_class'] == 'reached']
        driven = [r for r in rows if r['driving_min_sampled_clearance_m'] != '']
        measured = [r for r in plans if r['planner'] == planner]
        times = [float(r['planning_time_ms']) for r in measured]
        summary.append({
            'planner': planner, 'episodes': len(rows), 'reached': len(reached),
            'collisions': sum(r['collision'] == 'True' for r in rows),
            'timeouts': sum(r['simulation_status'] == 'timeout' for r in rows),
            'planning_failures': sum(r['planning_status'] != 'success' for r in rows),
            'planning_calls': len(measured),
            'smoothing_accepted': sum(a['planner'] == planner and a['smoothing'] == 'accepted'
                                      for a in acceptance),
            'success_median_tracking_rmse_m': median_or_none(
                [float(r['tracking_rmse_m']) for r in reached]),
            'success_median_completion_time_s': median_or_none(
                [float(r['completion_time_s']) for r in reached]),
            'driven_median_min_clearance_m': median_or_none(
                [float(r['driving_min_sampled_clearance_m']) for r in driven]),
            'planning_time_ms_median': median_or_none(times),
            'planning_time_ms_p95': float(np.quantile(times, .95)) if times else None,
        })
        for criterion, selected in (
            ('failure', [r for r in rows if r['failure_class'] != 'reached']),
            ('highest_reached_rmse', sorted(reached, key=lambda r: float(r['tracking_rmse_m']),
                                            reverse=True)[:3]),
            ('lowest_driving_clearance', sorted(
                driven, key=lambda r: float(r['driving_min_sampled_clearance_m']))[:3]),
        ):
            worst += [{'criterion': criterion, **r} for r in selected]
        pairs = [r for r in paired if r['planner'] == planner]
        if pairs:
            effects.append(paired_effect(pairs, planner=planner, baseline='astar', family='all'))
            for family in FAMILIES:
                effects.append(paired_effect([r for r in pairs if r['family'] == family],
                                             planner=planner, baseline='astar', family=family))
        for case in sorted({r['case'] for r in rows}):
            group = [r for r in rows if r['case'] == case]
            groups.append({'case': case, 'family': group[0]['family'], 'planner': planner,
                           'episodes': len(group),
                           'reached': sum(r['failure_class'] == 'reached' for r in group),
                           'failure_classes': ';'.join(sorted({r['failure_class'] for r in group}))})

    outcome = {(r['case'], r['simulation_seed'], r['planner']): r['failure_class'] == 'reached'
               for r in episodes}
    keys = sorted({(case, seed) for case, seed, _ in outcome})
    versus_hybrid = {
        'pairs': len(keys),
        'candidate_only': sum(outcome[k + (CANDIDATE_NAME,)] and not outcome[k + ('hybrid_astar',)]
                              for k in keys),
        'hybrid_only': sum(outcome[k + ('hybrid_astar',)] and not outcome[k + (CANDIDATE_NAME,)]
                           for k in keys),
        'both': sum(outcome[k + ('hybrid_astar',)] and outcome[k + (CANDIDATE_NAME,)] for k in keys)}

    family_effects = [e for e in effects if e['planner'] == CANDIDATE_NAME and e['family'] != 'all']
    overall = next(e for e in effects if e['planner'] == CANDIDATE_NAME and e['family'] == 'all')
    supported = (overall['reach_wins'] > overall['reach_losses']
                 and all(e['reach_wins'] >= e['reach_losses'] for e in family_effects))
    decision = {'rule': 'wins > losses overall and no family net loss vs A*',
                'overall_wins': overall['reach_wins'], 'overall_losses': overall['reach_losses'],
                'family_net': {e['family']: e['reach_wins'] - e['reach_losses']
                               for e in family_effects},
                'held_out_supported': supported}

    write_csv(folder / 'episodes.csv', episodes)
    write_csv(folder / 'planning.csv', plans)
    write_csv(folder / 'paired.csv', paired)
    write_csv(folder / 'summary.csv', summary)
    write_csv(folder / 'effects.csv', effects)
    write_csv(folder / 'worst.csv', worst)
    write_csv(folder / 'cases.csv', groups)
    write_csv(folder / 'acceptance.csv', acceptance)
    return {'outcomes': summary, 'decision': decision, 'versus_hybrid': versus_hybrid}


def acceptance_audit(scenario_path, case, stored_lengths):
    """Re-plan candidate/ablation deterministically; acceptance is not stored in batches."""
    scenario = load_scenario(scenario_path)
    grid = load_occupancy_map(scenario.map_path).grid
    rows = []
    for classname in (CANDIDATE, ABLATION):
        planner = load_custom_planner(f'{PLUGIN}:{classname}')[0]
        result = planner.plan(grid, scenario.start, scenario.goal, timeout_s=scenario.timeout_s)
        length = (float(np.hypot(*np.diff([(p.x, p.y) for p in result.path.poses], axis=0).T).sum())
                  if result.path else None)
        stored = stored_lengths.get(planner.name)
        rows.append({
            'case': case, 'planner': planner.name, 'status': result.status.value,
            'smoothing': result.metadata.get('smoothing'),
            'smoothing_reason': result.metadata.get('smoothing_reason', ''),
            'smoothed_max_curvature_per_m': result.metadata.get('smoothed_max_curvature_per_m', ''),
            'smoothed_min_footprint_clearance_m': result.metadata.get(
                'smoothed_min_footprint_clearance_m', ''),
            'replanned_path_length_m': length, 'stored_path_length_m': stored,
            'matches_stored_plan': (length is not None and stored is not None
                                    and abs(length - stored) <= 1e-9),
        })
    return rows


def execute(folder):
    protocol = verify_seal(folder)
    # Exclusive claim precedes all planning; an interrupted run is never silently repeated.
    write_json(folder / 'execution_started.json', {'seal_sha256': digest(folder / 'seal.json')})
    started = perf_counter()
    episodes, plans, pairs, acceptance = [], [], [], []
    for member in protocol['members']:
        verify_seal(folder)
        case = f'{member["family"]}_{member["variant"]}_q{member["query"]}'
        target = folder / 'batches' / case
        summary = target / 'comparison.csv'
        scenario = folder / member['scenario']
        command = [str(scenario), '--output', str(summary),
                   '--simulation-seeds', *map(str, protocol['seeds']),
                   '--custom-planner', f'{PLUGIN}:{CANDIDATE}',
                   '--custom-planner', f'{PLUGIN}:{ABLATION}']
        for setting, value in protocol['noise'].items():
            command += ['--' + setting, str(value)]
        experiment(command)
        analyze([str(summary), '--baseline', 'astar', '--output-dir', str(target / 'analysis')])
        report([str(summary), '--output', str(target / 'comparison.png')])
        dimensions = {'family': member['family'], 'variant': member['variant'],
                      'query': member['query'], 'case': case}
        local = read_csv(target / 'analysis/episodes.csv')
        episodes += [dimensions | r for r in local]
        pairs += [dimensions | r for r in read_csv(target / 'analysis/paired.csv')]
        seen = {}
        for row in local:
            if row['planner'] not in seen:
                seen[row['planner']] = row
                plans.append(dimensions | {key: row[key] for key in (
                    'planner', 'planning_status', 'planning_time_ms', 'expanded_nodes',
                    'path_length_m', 'total_absolute_turn_rad', 'max_discrete_curvature_per_m',
                    'min_sampled_footprint_clearance_m')})
        stored = {name: float(row['path_length_m']) for name, row in seen.items()
                  if row['path_length_m'] != ''}
        acceptance += acceptance_audit(scenario, case, stored)
        verify_seal(folder)
    result = aggregate(folder, episodes, plans, pairs, acceptance)
    verify_seal(folder)
    result['wall_time_s'] = perf_counter() - started
    write_json(folder / 'summary.json', result)
    write_json(folder / 'complete.json', {
        'seal_sha256': digest(folder / 'seal.json'), 'status': 'complete',
        'artifact_sha256': {str(path.relative_to(folder).as_posix()): digest(path)
                            for path in sorted(folder.rglob('*')) if path.is_file()},
    })
    print(f'completed sealed evaluation -> {folder}', flush=True)
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
        result = execute(folder)
        print(json.dumps({'decision': result['decision'], 'versus_hybrid': result['versus_hybrid']},
                         indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
