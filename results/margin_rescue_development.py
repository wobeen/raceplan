"""Development comparison of margin-raised lead-in rescue on new procedural maps.

Pre-registered in docs/MARGIN_RESCUE_DEVELOPMENT.md under research policy v2.
Inputs are generated at run time by ``generate`` from the committed seed range
DEV_SEEDS; no input existed when the candidate parameters were fixed.  Seeds
from HELD_OUT_SEED_START upward are reserved for a later held-out and are never
generated here.  The selection rule is computed by ``decide`` from saved results.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from math import ceil
from pathlib import Path
import platform
import sys
from time import perf_counter

import numpy as np
from PIL import Image
import yaml

from raceplan.analyze import main as analyze
from raceplan.common import (OccupancyGrid, Pose2D, footprint_in_collision, load_occupancy_map,
                             load_scenario)
from raceplan.defaults import baseline_vehicle
from raceplan.experiment import main as experiment
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


previous = _load('_leadin_dev_runner', 'results/leadin_rescue_development.py')
identity = _load('_query_identity_v2', 'results/turn_aware_query_identity_v2.py')

BASE_PLUGIN = ROOT / 'examples/smoothed_astar_planner.py'
LEADIN_PLUGIN = ROOT / 'examples/leadin_rescue_planner.py'
MARGIN_PLUGIN = ROOT / 'examples/margin_rescue_planner.py'
FAMILIES = ('staggered_windows', 'offset_islands', 'slalom_walls')
DEV_SEEDS = tuple(range(1000, 1012))
HELD_OUT_SEED_START = 2000
RESOLUTION = 0.2
SHAPE = (36, 52)
TIMEOUT = 2.0
SEEDS = (11, 12, 13)
NOISE = previous.NOISE
CUSTOM = [(BASE_PLUGIN, 'SmoothedLowClearance'), (LEADIN_PLUGIN, 'LeadInRescueK3'),
          (MARGIN_PLUGIN, 'MarginRescue08'), (MARGIN_PLUGIN, 'MarginRescue11'),
          (MARGIN_PLUGIN, 'MarginOnly08')]
REFERENCE = 'smoothed_low_clearance'
PREVIOUS = 'leadin_rescue_k3'
CANDIDATES = ('margin_rescue_08', 'margin_rescue_11')
ABLATION = 'margin_only_08'
PLANNERS = ('astar', 'hybrid_astar', REFERENCE, PREVIOUS, *CANDIDATES, ABLATION)
MIN_REFERENCE_STRATUM = 6
MIN_GAIN = 2
MIN_GAIN_FRACTION = 0.10
NEAR_DUPLICATE_IOU = 0.9
DECISION_RULE = (
    'query reached iff >=2 of 3 seeds reached. Any acceptance-audit mismatch invalidates the '
    f'run. Undecidable if the reference reaches fewer than {MIN_REFERENCE_STRATUM} queries. '
    'A candidate is eligible iff it loses no query reached by the reference or by A* and '
    f'its net query gain over the reference is >= max({MIN_GAIN}, ceil({MIN_GAIN_FRACTION} x '
    'queries)). Among eligible candidates pick highest net gain, then more accepted queries, '
    'then lower planning-time P95, then the smaller margin. The previous lead-in candidate, '
    'Hybrid A*, and the margin-only ablation are reported but never selectable.'
)
FOLLOW_UP = {
    'selected': f'stop; a held-out on generator seeds >= {HELD_OUT_SEED_START} needs explicit '
                'user approval',
    'none': 'record negative result; do not tune further on these inputs',
    'undecidable': 'record; no selection; no rerun in this step',
    'invalid_audit': 'record only; no rerun in this step; nondeterminism is a new step',
}


def snap(value: float, step: float = RESOLUTION) -> float:
    return round(round(value / step) * step, 10)


def rasterize(rectangles):
    yy, xx = np.indices(SHAPE)
    left, bottom = xx * RESOLUTION, yy * RESOLUTION
    occupied = np.zeros(SHAPE, dtype=bool)
    for x0, y0, x1, y1 in rectangles:
        occupied |= ((left < x1 - 1e-9) & (left + RESOLUTION > x0 + 1e-9)
                     & (bottom < y1 - 1e-9) & (bottom + RESOLUTION > y0 + 1e-9))
    return occupied


def interior(family: str, rng: np.random.Generator):
    """Randomized obstacles of one family inside the 10.4 x 7.2 m bordered map."""
    if family == 'staggered_windows':
        while True:
            centres = rng.uniform(2.0, 5.2, size=2)
            if abs(centres[0] - centres[1]) >= 1.6:
                break
        rectangles = []
        for x, centre in zip((snap(rng.uniform(2.6, 3.6)), snap(rng.uniform(6.2, 7.2))), centres):
            half = snap(rng.uniform(2.0, 2.4)) / 2
            rectangles += [(x, 0.2, x + 0.6, snap(centre - half)),
                           (x, snap(centre + half), x + 0.6, 7.0)]
        return rectangles
    if family == 'offset_islands':
        low_first = bool(rng.integers(2))
        rectangles = []
        for index, anchor in enumerate((2.4, 4.8, 7.2)):
            x = snap(anchor + rng.uniform(-0.2, 0.2))
            width, height = snap(rng.uniform(1.2, 1.6)), snap(rng.uniform(1.8, 2.2))
            if (index % 2 == 0) == low_first:
                bottom = snap(rng.uniform(1.0, 1.6))
                rectangles.append((x, bottom, x + width, bottom + height))
            else:
                top = snap(rng.uniform(5.6, 6.2))
                rectangles.append((x, top - height, x + width, top))
        return rectangles
    if family == 'slalom_walls':
        bottom_first = bool(rng.integers(2))
        rectangles = []
        for index, x in enumerate((snap(rng.uniform(3.0, 3.8)), snap(rng.uniform(6.4, 7.2)))):
            if (index == 0) == bottom_first:
                rectangles.append((x, 0.2, x + 0.4, snap(rng.uniform(4.2, 4.8))))
            else:
                rectangles.append((x, snap(rng.uniform(2.4, 3.0)), x + 0.4, 7.0))
        return rectangles
    raise ValueError(f'unknown family: {family}')


def generate(seed: int):
    """Deterministic map and two queries for one generator seed."""
    if seed >= HELD_OUT_SEED_START:
        raise ValueError('held-out seeds are reserved')
    rng = np.random.default_rng(seed)
    family = FAMILIES[(seed - DEV_SEEDS[0]) % len(FAMILIES)]
    rectangles = [(0, 0, 10.4, 0.2), (0, 7.0, 10.4, 7.2), (0, 0, 0.2, 7.2),
                  (10.2, 0, 10.4, 7.2)] + interior(family, rng)
    grid = OccupancyGrid(rasterize(rectangles), RESOLUTION)
    queries = []
    for low_to_high in (True, False):
        for _ in range(50):
            low, high = snap(rng.uniform(1.4, 1.8), 0.1), snap(rng.uniform(5.4, 5.8), 0.1)
            start_y, goal_y = (low, high) if low_to_high else (high, low)
            start, goal = Pose2D(1.2, start_y, 0.0), Pose2D(9.2, goal_y, 0.0)
            if not any(footprint_in_collision(grid, pose, baseline_vehicle())
                       for pose in (start, goal)):
                queries.append((start, goal))
                break
        else:
            raise ValueError(f'seed {seed}: no collision-free query')
    return family, grid, queries, rectangles


def committed_inventory():
    """Maps and queries from Git-tracked YAML only (ignored raw results excluded)."""
    names = previous.git('ls-files', '--', '*.yaml').splitlines()
    grids, queries = {}, set()
    for name in names:
        path = ROOT / name
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            continue
        if 'image' in data:
            grids[name] = load_occupancy_map(path).grid
        elif {'map', 'start', 'goal'} <= data.keys():
            scenario = load_scenario(path)
            grid = load_occupancy_map(scenario.map_path).grid
            queries.add(identity.query_fingerprint_v2(grid, scenario.start, scenario.goal))
    return grids, queries


def novelty(generated, inventory):
    """Exact map/query duplicates and near-duplicate maps (IoU of occupied cells)."""
    grids, queries = inventory
    report, seen = [], set()
    for seed, (family, grid, pairs, _) in generated.items():
        fingerprint = identity.grid_fingerprint_v2(grid)
        best = max((float((grid.occupied & other.occupied).sum()
                          / (grid.occupied | other.occupied).sum()), name)
                   for name, other in grids.items()
                   if other.occupied.shape == grid.occupied.shape) if grids else (0.0, '')
        query_hashes = [identity.query_fingerprint_v2(grid, s, g) for s, g in pairs]
        report.append({'seed': seed, 'family': family, 'map_sha256': fingerprint,
                       'max_iou': best[0], 'max_iou_with': best[1],
                       'exact_map_duplicate': fingerprint in seen or any(
                           identity.grid_fingerprint_v2(other) == fingerprint
                           for other in grids.values()),
                       'exact_query_duplicate': any(q in queries for q in query_hashes)})
        seen.add(fingerprint)
    bad = [r for r in report if r['exact_map_duplicate'] or r['exact_query_duplicate']
           or r['max_iou'] >= NEAR_DUPLICATE_IOU]
    return report, bad


def write_inputs(folder: Path, generated):
    names = []
    for seed, (family, grid, pairs, rectangles) in generated.items():
        member = folder / f'seed{seed}_{family}'
        member.mkdir(parents=True)
        image = np.flipud(np.where(grid.occupied, 0, 255)).astype('uint8')
        Image.fromarray(image).save(member / 'map.pgm')
        (member / 'map.yaml').write_text(yaml.safe_dump({
            'image': 'map.pgm', 'resolution': RESOLUTION, 'origin': [0.0, 0.0, 0.0],
            'source': f'RacePlan margin-rescue development generator seed {seed}',
            'license': 'CC0-1.0'}), encoding='utf-8')
        previous.write_json(member / 'geometry.json', {'rectangles_m': rectangles})
        for index, (start, goal) in enumerate(pairs):
            scenario = member / f'q{index}.yaml'
            scenario.write_text(yaml.safe_dump({
                'name': f'seed{seed}_{family}_q{index}', 'map': 'map.yaml',
                'start': [start.x, start.y, start.yaw], 'goal': [goal.x, goal.y, goal.yaw],
                'map_seed': seed, 'simulation_seed': SEEDS[0], 'timeout_s': TIMEOUT}),
                encoding='utf-8')
            identity.validate_scenario_roundtrip(grid, start, goal, scenario)
            names.append(scenario)
    return names


def decide(episodes, audit_rows, planning_p95):
    """Apply the pre-registered query-level rule; returns the decision record."""
    counts = previous.query_outcomes(episodes)
    cases = sorted({row['case'] for row in episodes})
    reached = {(case, planner): counts[case, planner] >= 2
               for case in cases for planner in PLANNERS}
    reference_reached = [c for c in cases if reached[c, REFERENCE]]
    astar_reached = [c for c in cases if reached[c, 'astar']]
    required = max(MIN_GAIN, ceil(MIN_GAIN_FRACTION * len(cases)))
    audit_ok = bool(audit_rows) and all(row['matches_stored_path'] for row in audit_rows)
    decidable = audit_ok and len(reference_reached) >= MIN_REFERENCE_STRATUM
    rows = []
    for planner in (*CANDIDATES, ABLATION, PREVIOUS, 'hybrid_astar'):
        losses_reference = [c for c in reference_reached if not reached[c, planner]]
        losses_astar = [c for c in astar_reached if not reached[c, planner]]
        gains = [c for c in cases if reached[c, planner] and not reached[c, REFERENCE]]
        net = len(gains) - len(losses_reference)
        rows.append({
            'planner': planner, 'queries_reached': sum(reached[c, planner] for c in cases),
            'gains_vs_reference': gains, 'losses_vs_reference': losses_reference,
            'losses_vs_astar': losses_astar, 'net_gain_vs_reference': net,
            'accepted_queries': sum(row['planner'] == planner and row['smoothing'] == 'accepted'
                                    for row in audit_rows),
            'planning_time_ms_p95': planning_p95.get(planner),
            'eligible': (decidable and planner in CANDIDATES and not losses_reference
                         and not losses_astar and net >= required),
        })
    if not audit_ok:
        verdict, selected = 'invalid_audit', None
    elif not decidable:
        verdict, selected = 'undecidable', None
    else:
        eligible = sorted((r for r in rows if r['eligible']), key=lambda r: (
            -r['net_gain_vs_reference'], -r['accepted_queries'],
            r['planning_time_ms_p95'] if r['planning_time_ms_p95'] is not None else float('inf'),
            CANDIDATES.index(r['planner'])))
        verdict, selected = ('selected', eligible[0]['planner']) if eligible else ('none', None)
    return {'rule': DECISION_RULE, 'queries': len(cases),
            'reference_reached_queries': len(reference_reached),
            'astar_reached_queries': len(astar_reached), 'required_net_gain': required,
            'audit_all_match': audit_ok,
            'audit_mismatches': [f"{r['case']}/{r['planner']}" for r in audit_rows
                                 if not r['matches_stored_path']],
            'rescue_timeouts': dict(Counter(r['planner'] for r in audit_rows
                                            if r.get('rescue') == 'timeout')),
            'candidates': rows, 'verdict': verdict, 'selected': selected,
            'follow_up': FOLLOW_UP[verdict]}


def run(output: Path, prereg_commit: str, seeds=DEV_SEEDS):
    if output.exists():
        raise ValueError('output directory already exists')
    state = previous.repository_state(prereg_commit)
    generated = {seed: generate(seed) for seed in seeds}
    report, bad = novelty(generated, committed_inventory())
    output.mkdir(parents=True)
    previous.write_json(output / 'novelty.json', {'members': report,
                                                  'near_duplicate_iou': NEAR_DUPLICATE_IOU})
    if bad:
        raise ValueError(f'generated inputs duplicate committed inputs: {bad}')
    inputs = write_inputs(output / 'inputs', generated)
    sources = sorted((ROOT / 'src/raceplan').rglob('*.py')) + [
        BASE_PLUGIN, LEADIN_PLUGIN, MARGIN_PLUGIN, Path(__file__).resolve(),
        ROOT / 'results/leadin_rescue_development.py',
        ROOT / 'results/turn_aware_query_identity_v2.py']
    protocol = {
        'kind': 'development_selection_on_new_procedural_inputs_not_held_out',
        'policy': 'research policy v2 (docs/COMMIT_PLAN.md, docs/FEATURE_SCOPE.md)',
        **state, 'uv_lock_sha256': previous.digest(ROOT / 'uv.lock'),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'raceplan_import_path': Path(sys.modules['raceplan'].__file__).resolve().parent.as_posix(),
        'generator_seeds': list(seeds), 'held_out_seed_start': HELD_OUT_SEED_START,
        'seeds': list(SEEDS), 'noise': NOISE, 'planners': list(PLANNERS),
        'reference': REFERENCE, 'candidates': list(CANDIDATES), 'ablation': ABLATION,
        'decision_rule': DECISION_RULE, 'follow_up': FOLLOW_UP,
        'source_sha256': {previous.rel(p): previous.digest(p) for p in sources},
        'input_sha256': {path.relative_to(output).as_posix(): previous.digest(path)
                         for path in sorted((output / 'inputs').rglob('*')) if path.is_file()},
    }
    previous.write_json(output / 'protocol_start.json', protocol)
    started = perf_counter()
    episodes, plans, audit_rows = [], [], []
    for scenario in inputs:
        case = f'{scenario.parent.name}__{scenario.stem}'
        target = output / 'batches' / case
        target.mkdir(parents=True)
        summary = target / 'comparison.csv'
        command = [str(scenario), '--output', str(summary), '--planners', 'astar', 'hybrid_astar',
                   '--simulation-seeds', *map(str, SEEDS)]
        for plugin, classname in CUSTOM:
            command += ['--custom-planner', f'{plugin}:{classname}']
        for setting, value in NOISE.items():
            command += ['--' + setting, str(value)]
        experiment(command)
        analyze([str(summary), '--baseline', 'astar', '--output-dir', str(target / 'analysis')])
        local = previous.read_csv(target / 'analysis/episodes.csv')
        episodes += [{'case': case, **row} for row in local]
        seen = set()
        for row in local:
            if row['planner'] not in seen:
                seen.add(row['planner'])
                plans.append({'planner': row['planner'], 'planning_time_ms': row['planning_time_ms']})
        stored = {}
        for row in previous.read_csv(target / 'comparison_paths.csv'):
            stored.setdefault(row['plan_id'], []).append(
                (float(row['x_m']), float(row['y_m']), float(row['yaw_rad'])))
        audit_rows += audit(scenario, case, stored)

    planning_p95, summary_rows = {}, []
    for planner in PLANNERS:
        rows = [r for r in episodes if r['planner'] == planner]
        times = [float(r['planning_time_ms']) for r in plans
                 if r['planner'] == planner and r['planning_time_ms'] != '']
        planning_p95[planner] = float(np.quantile(times, .95)) if times else None
        counts = Counter(r['failure_class'] for r in rows)
        summary_rows.append({
            'planner': planner, 'episodes': len(rows), 'reached': counts['reached'],
            'collisions': counts['driving_collision'] + counts['initial_collision'],
            'timeouts': counts['timeout'],
            'planning_failures': sum(v for k, v in counts.items() if k.startswith('planning_')),
            'accepted_queries': sum(a['planner'] == planner and a['smoothing'] == 'accepted'
                                    for a in audit_rows),
            'planning_time_ms_median': float(np.median(times)) if times else None,
            'planning_time_ms_p95': planning_p95[planner],
        })
    decision = decide(episodes, audit_rows, planning_p95)
    counts = previous.query_outcomes(episodes)
    query_rows = [{'case': case, **{p: counts[case, p] for p in PLANNERS}}
                  for case in sorted({r['case'] for r in episodes})]
    previous.write_csv(output / 'summary.csv', summary_rows)
    previous.write_csv(output / 'queries.csv', query_rows)
    previous.write_csv(output / 'acceptance.csv', audit_rows)
    previous.write_csv(output / 'episodes.csv', episodes)
    previous.write_json(output / 'protocol.json', protocol | {
        'episodes': len(episodes), 'wall_time_s': perf_counter() - started,
        'acceptance_audit_all_match': decision['audit_all_match']})
    previous.write_json(output / 'decision.json', decision)
    return summary_rows, decision


def audit(scenario: Path, case: str, stored):
    """Deterministic re-plan of every post-processing planner, compared pose for pose."""
    loaded = load_scenario(scenario)
    grid = load_occupancy_map(loaded.map_path).grid
    rows = []
    for plugin, classname in CUSTOM:
        planner = load_custom_planner(f'{plugin}:{classname}')[0]
        try:
            result = planner.plan(grid, loaded.start, loaded.goal, timeout_s=loaded.timeout_s)
        except Exception as exc:  # the experiment records these as planning_error rows
            rows.append({'case': case, 'planner': planner.name, 'status': 'planning_error',
                         'smoothing': '', 'smoothing_reason': type(exc).__name__, 'rescue': '',
                         'smoothed_min_footprint_clearance_m': '',
                         'matches_stored_path': stored.get(planner.name, []) == []})
            continue
        replanned = [(p.x, p.y, p.yaw) for p in result.path.poses] if result.path else []
        rows.append({
            'case': case, 'planner': planner.name, 'status': result.status.value,
            'smoothing': result.metadata.get('smoothing'),
            'smoothing_reason': result.metadata.get('smoothing_reason', ''),
            'rescue': result.metadata.get('rescue', ''),
            'smoothed_min_footprint_clearance_m': result.metadata.get(
                'smoothed_min_footprint_clearance_m', ''),
            'matches_stored_path': replanned == stored.get(planner.name, []),
        })
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--prereg-commit', required=True)
    args = parser.parse_args(argv)
    summary, decision = run(args.output_dir.resolve(), args.prereg_commit)
    print(json.dumps({'summary': summary, 'decision': decision}, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
