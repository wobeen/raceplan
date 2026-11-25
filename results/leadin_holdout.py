"""Held-out evaluation of ``leadin_rescue_k3`` on procedural maps from seeds 2000+.

Pre-registered in docs/LEADIN_HOLDOUT.md under research policy v2.  The map and
query generator is the committed development generator (results/
margin_rescue_development.py) applied to the reserved seed range.  Queries are
stratified by a planning-only classification of the reference post-processor
(accepted vs rejected); no candidate is driven before that selection is fixed
by the code below.  The verdict is computed by ``decide``.
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

from raceplan.common import OccupancyGrid, Pose2D, load_occupancy_map, load_scenario
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import Clearance
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]


def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


development = _load('_margin_dev_runner', 'results/margin_rescue_development.py')
previous = development.previous
identity = development.identity

BASE_PLUGIN = development.BASE_PLUGIN
LEADIN_PLUGIN = development.LEADIN_PLUGIN
POOL_SEEDS = tuple(range(2000, 3000))   # scanned in order until every family quota is full
PER_FAMILY = 20
DEVELOPMENT_GENERATED = tuple(development.DEV_SEEDS) + (1999,)   # development run and its smoke test
SMOKE_SEEDS = (1997, 1998)                                       # this runner's smoke test
SIMULATION_SEEDS = (41, 42, 43)
NOISE = development.NOISE
CUSTOM = [(BASE_PLUGIN, 'SmoothedLowClearance'), (LEADIN_PLUGIN, 'LeadInRescueK3')]
REFERENCE = 'smoothed_low_clearance'
CANDIDATE = 'leadin_rescue_k3'
PLANNERS = ('astar', 'hybrid_astar', REFERENCE, CANDIDATE)
TARGET_REJECTED = 16
TARGET_ACCEPTED = 8
MIN_REJECTED = 8
MIN_GAIN = 2
MIN_GAIN_FRACTION = 0.25
MIN_REGRESSION_STRATUM = 2
DECISION_RULE = (
    'query reached iff >=2 of 3 seeds reached. Any acceptance-audit mismatch, or any accepted '
    'query where the candidate path differs from the reference path, invalidates the run. '
    f'Undecidable if fewer than {MIN_REJECTED} selected queries are reference-rejected. '
    'Held-out supported iff the candidate loses no query reached by the reference or by A* '
    f'and its net query gain over the reference is >= max({MIN_GAIN}, ceil({MIN_GAIN_FRACTION} '
    'x rejected queries)). No-regression evidence is "tested" only if at least '
    f'{MIN_REGRESSION_STRATUM} rejected queries are reached by the reference fallback.'
)
FOLLOW_UP = {
    'supported': 'record; promotion still needs a second independent held-out and the '
                 'FEATURE_SCOPE promotion criteria; no rerun or tuning on these inputs',
    'not_supported': 'record negative held-out; candidate stays research archive',
    'undecidable': 'record; no rerun in this step',
    'invalid_audit': 'record only; no rerun in this step',
    'aborted': 'record only; no rerun in this step',
}


def generate(seed: int):
    """The development generator applied to any non-development seed.

    Same obstacle ranges (``development.interior``), raster, endpoint clearance
    rule and query ranges; the family cycles with the seed's offset in the pool.
    """
    if seed in development.DEV_SEEDS:
        raise ValueError('development seeds are exposed')
    rng = np.random.default_rng(seed)
    family = development.FAMILIES[(seed - POOL_SEEDS[0]) % len(development.FAMILIES)]
    rectangles = [(0, 0, 10.4, 0.2), (0, 7.0, 10.4, 7.2), (0, 0, 0.2, 7.2),
                  (10.2, 0, 10.4, 7.2)] + development.interior(family, rng)
    grid = OccupancyGrid(development.rasterize(rectangles), development.RESOLUTION)
    clearance = Clearance(grid)
    queries = []
    for low_to_high in (True, False):
        for _ in range(50):
            low = development.snap(rng.uniform(1.4, 1.8), 0.1)
            high = development.snap(rng.uniform(5.4, 5.8), 0.1)
            start_y, goal_y = (low, high) if low_to_high else (high, low)
            start, goal = Pose2D(1.2, start_y, 0.0), Pose2D(9.2, goal_y, 0.0)
            if all(clearance.footprint(pose, baseline_vehicle())
                   >= development.MIN_ENDPOINT_CLEARANCE_M for pose in (start, goal)):
                queries.append((start, goal))
                break
        else:
            queries.append(None)   # recorded; the query is unavailable, not redrawn
    return family, grid, queries, rectangles


def inventory_with_development():
    """Committed inventory plus every map the development step and smoke tests generated."""
    grids, queries = development.committed_inventory()
    generated = ({seed: development.generate(seed) for seed in DEVELOPMENT_GENERATED}
                 | {seed: generate(seed) for seed in SMOKE_SEEDS})
    for seed, (family, grid, pairs, _) in generated.items():
        grids[f'generated seed {seed}'] = grid
        queries |= {identity.query_fingerprint_v2(grid, *pair) for pair in pairs if pair is not None}
    return grids, queries


def classify(pool):
    """Planning-only reference classification of every available pool query."""
    reference = load_custom_planner(f'{BASE_PLUGIN}:SmoothedLowClearance')[0]
    rows = []
    for seed, (family, grid, pairs, _) in pool.items():
        for index, pair in enumerate(pairs):
            if pair is None:
                rows.append({'seed': seed, 'query': index, 'family': family,
                             'reference': 'unavailable'})
                continue
            result = reference.plan(grid, *pair, timeout_s=development.TIMEOUT)
            label = (result.metadata.get('smoothing', 'failed')
                     if result.status.value == 'success' else f'failed:{result.status.value}')
            rows.append({'seed': seed, 'query': index, 'family': family, 'reference': label})
    return rows


def select(classification):
    """First TARGET_REJECTED rejected and TARGET_ACCEPTED accepted queries in pool order."""
    rejected = [r for r in classification if r['reference'] == 'rejected'][:TARGET_REJECTED]
    accepted = [r for r in classification if r['reference'] == 'accepted'][:TARGET_ACCEPTED]
    return sorted(rejected + accepted, key=lambda r: (r['seed'], r['query']))


def write_inputs(folder: Path, pool, selected):
    paths = []
    for row in selected:
        family, grid, pairs, rectangles = pool[row['seed']]
        member = folder / f"seed{row['seed']}_{family}"
        if not member.exists():
            member.mkdir(parents=True)
            image = np.flipud(np.where(grid.occupied, 0, 255)).astype('uint8')
            Image.fromarray(image).save(member / 'map.pgm')
            (member / 'map.yaml').write_text(yaml.safe_dump({
                'image': 'map.pgm', 'resolution': development.RESOLUTION,
                'origin': [0.0, 0.0, 0.0], 'license': 'CC0-1.0',
                'source': f"RacePlan lead-in held-out generator seed {row['seed']}"}),
                encoding='utf-8')
            previous.write_json(member / 'geometry.json', {'rectangles_m': rectangles})
        start, goal = pairs[row['query']]
        scenario = member / f"q{row['query']}.yaml"
        scenario.write_text(yaml.safe_dump({
            'name': f"seed{row['seed']}_{family}_q{row['query']}", 'map': 'map.yaml',
            'start': [start.x, start.y, start.yaw], 'goal': [goal.x, goal.y, goal.yaw],
            'map_seed': row['seed'], 'simulation_seed': SIMULATION_SEEDS[0],
            'timeout_s': development.TIMEOUT}), encoding='utf-8')
        identity.validate_scenario_roundtrip(grid, start, goal, scenario)
        paths.append(scenario)
    return paths


def decide(episodes, audit_rows, stratum, planning_p95):
    """Pre-registered held-out verdict plus the FEATURE_SCOPE promotion checklist."""
    counts = previous.query_outcomes(episodes)
    cases = sorted({row['case'] for row in episodes})
    reached = {(case, planner): counts[case, planner] >= 2
               for case in cases for planner in PLANNERS}
    audit = {(row['case'], row['planner']): row for row in audit_rows}
    rejected = [c for c in cases if stratum.get(c) == 'rejected']
    accepted = [c for c in cases if stratum.get(c) == 'accepted']
    regression_stratum = [c for c in rejected if reached[c, REFERENCE]]
    reference_reached = [c for c in cases if reached[c, REFERENCE]]
    astar_reached = [c for c in cases if reached[c, 'astar']]
    losses_reference = [c for c in reference_reached if not reached[c, CANDIDATE]]
    losses_astar = [c for c in astar_reached if not reached[c, CANDIDATE]]
    gains = [c for c in cases if reached[c, CANDIDATE] and not reached[c, REFERENCE]]
    net = len(gains) - len(losses_reference)
    required = max(MIN_GAIN, ceil(MIN_GAIN_FRACTION * len(rejected)))
    accepted_identical = all(audit.get((c, CANDIDATE), {}).get('path_digest')
                             == audit.get((c, REFERENCE), {}).get('path_digest')
                             for c in accepted)
    audit_ok = (bool(audit_rows) and all(r['matches_stored_path'] for r in audit_rows)
                and accepted_identical)
    if not audit_ok:
        verdict = 'invalid_audit'
    elif len(rejected) < MIN_REJECTED:
        verdict = 'undecidable'
    elif not losses_reference and not losses_astar and net >= required:
        verdict = 'supported'
    else:
        verdict = 'not_supported'
    hybrid_net = (sum(reached[c, CANDIDATE] and not reached[c, 'hybrid_astar'] for c in cases)
                  - sum(reached[c, 'hybrid_astar'] and not reached[c, CANDIDATE] for c in cases))
    post_processed = sum(audit.get((c, CANDIDATE), {}).get('smoothing') == 'accepted'
                         for c in cases)
    timeout = development.TIMEOUT * 1000
    promotion = {
        'queries_at_least_24': len(cases) >= 24,
        'astar_success_query_share_at_least_30pct': (len(astar_reached) / len(cases) >= 0.30
                                                     if cases else False),
        'no_loss_on_astar_success_queries': not losses_astar,
        'reach_rate_gain_at_least_25pp': (net / len(cases) >= 0.25 if cases else False),
        'hybrid_query_net_non_negative': hybrid_net >= 0,
        'post_processing_acceptance_at_least_75pct': (post_processed / len(cases) >= 0.75
                                                      if cases else False),
        'planning_p95_at_most_25pct_of_timeout': (planning_p95.get(CANDIDATE) is not None
                                                  and planning_p95[CANDIDATE] <= 0.25 * timeout),
    }
    return {'rule': DECISION_RULE, 'queries': len(cases), 'rejected_queries': rejected,
            'accepted_queries': accepted, 'rejected_and_fallback_reached': regression_stratum,
            'no_regression_evidence': ('tested' if len(regression_stratum) >= MIN_REGRESSION_STRATUM
                                       else 'untestable'),
            'reference_reached_queries': len(reference_reached),
            'astar_reached_queries': len(astar_reached),
            'hybrid_reached_queries': sum(reached[c, 'hybrid_astar'] for c in cases),
            'candidate_reached_queries': sum(reached[c, CANDIDATE] for c in cases),
            'gains_vs_reference': gains, 'losses_vs_reference': losses_reference,
            'losses_vs_astar': losses_astar, 'net_gain_vs_reference': net,
            'required_net_gain': required, 'hybrid_query_net': hybrid_net,
            'rescued_queries': [c for c in cases
                                if audit.get((c, CANDIDATE), {}).get('rescue') == 'lead_in'],
            'audit_all_match': audit_ok, 'accepted_paths_identical': accepted_identical,
            'audit_mismatches': [f"{r['case']}/{r['planner']}" for r in audit_rows
                                 if not r['matches_stored_path']],
            'rescue_timeouts': sum(r.get('rescue') == 'timeout' for r in audit_rows),
            'promotion_checklist': promotion,
            'verdict': verdict, 'follow_up': FOLLOW_UP[verdict]}


def audit(scenario: Path, case: str, stored):
    """Deterministic re-plan of both post-processors, compared pose for pose."""
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
                         'path_digest': '[]',
                         'matches_stored_path': stored.get(planner.name, []) == []})
            continue
        replanned = [(p.x, p.y, p.yaw) for p in result.path.poses] if result.path else []
        rows.append({'case': case, 'planner': planner.name, 'status': result.status.value,
                     'smoothing': result.metadata.get('smoothing'),
                     'smoothing_reason': result.metadata.get('smoothing_reason', ''),
                     'rescue': result.metadata.get('rescue', ''),
                     'path_digest': json.dumps(replanned),
                     'matches_stored_path': replanned == stored.get(planner.name, [])})
    return rows


def run_case(output: Path, scenario: Path, case: str):
    target = output / 'batches' / case
    target.mkdir(parents=True)
    summary = target / 'comparison.csv'
    command = [str(scenario), '--output', str(summary), '--planners', 'astar', 'hybrid_astar',
               '--simulation-seeds', *map(str, SIMULATION_SEEDS)]
    for plugin, classname in CUSTOM:
        command += ['--custom-planner', f'{plugin}:{classname}']
    for setting, value in NOISE.items():
        command += ['--' + setting, str(value)]
    development.experiment(command)
    development.analyze([str(summary), '--baseline', 'astar', '--output-dir',
                         str(target / 'analysis')])
    stored = {}
    for row in previous.read_csv(target / 'comparison_paths.csv'):
        stored.setdefault(row['plan_id'], []).append(
            (float(row['x_m']), float(row['y_m']), float(row['yaw_rad'])))
    return previous.read_csv(target / 'analysis/episodes.csv'), stored


def build_pool(seeds, inventory, per_family=PER_FAMILY):
    """First ``per_family`` novel maps of each family in seed order.

    A map is skipped if it is an exact or near duplicate (occupied-cell IoU >= 0.9) of the
    inventory or of a map already kept; skipped seeds are recorded, never redrawn.
    """
    grids, queries = inventory
    grids = dict(grids)
    kept, report, skipped = {}, [], []
    counts = Counter()
    for seed in seeds:
        family, grid, pairs, rectangles = generate(seed)
        if counts[family] >= per_family:
            continue
        rows, bad = development.novelty({seed: (family, grid, [p for p in pairs if p], rectangles)},
                                        (grids, queries))
        if bad:
            skipped.append(rows[0])
            continue
        kept[seed] = (family, grid, pairs, rectangles)
        report += rows
        grids[f'pool seed {seed}'] = grid
        counts[family] += 1
        if all(counts[f] >= per_family for f in development.FAMILIES):
            break
    return kept, report, skipped


def run(output: Path, prereg_commit: str, pool_seeds=POOL_SEEDS, per_family=PER_FAMILY):
    if output.exists():
        raise ValueError('output directory already exists')
    if set(pool_seeds) & set(DEVELOPMENT_GENERATED):
        raise ValueError('pool overlaps development seeds')
    state = previous.repository_state(prereg_commit)
    pool, report, skipped = build_pool(pool_seeds, inventory_with_development(), per_family)
    output.mkdir(parents=True)
    previous.write_json(output / 'novelty.json', {
        'members': report, 'skipped_near_or_exact_duplicates': skipped,
        'near_duplicate_iou': development.NEAR_DUPLICATE_IOU, 'per_family': per_family})
    started = perf_counter()
    classification = classify(pool)
    selected = select(classification)
    previous.write_csv(output / 'classification.csv', classification)
    inputs = write_inputs(output / 'inputs', pool, selected)
    stratum = {f"{p.parent.name}__{p.stem}": row['reference'] for p, row in zip(inputs, selected)}
    sources = sorted((ROOT / 'src/raceplan').rglob('*.py')) + [
        BASE_PLUGIN, LEADIN_PLUGIN, Path(__file__).resolve(),
        ROOT / 'results/margin_rescue_development.py',
        ROOT / 'results/leadin_rescue_development.py',
        ROOT / 'results/turn_aware_query_identity_v2.py']
    protocol = {
        'kind': 'held_out_evaluation', 'policy': 'research policy v2',
        **state, 'uv_lock_sha256': previous.digest(ROOT / 'uv.lock'),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'raceplan_import_path': Path(sys.modules['raceplan'].__file__).resolve().parent.as_posix(),
        'pool_seeds_scanned': [min(pool_seeds), max(pool_seeds)], 'pool_kept': sorted(pool),
        'development_generated_seeds': list(DEVELOPMENT_GENERATED),
        'smoke_seeds': list(SMOKE_SEEDS),
        'selection': {'target_rejected': TARGET_REJECTED, 'target_accepted': TARGET_ACCEPTED,
                      'selected': [f"{r['seed']}/q{r['query']}:{r['reference']}" for r in selected],
                      'pool_counts': dict(Counter(r['reference'] for r in classification))},
        'simulation_seeds': list(SIMULATION_SEEDS), 'noise': NOISE, 'planners': list(PLANNERS),
        'reference': REFERENCE, 'candidate': CANDIDATE, 'decision_rule': DECISION_RULE,
        'follow_up': FOLLOW_UP,
        'source_sha256': {previous.rel(p): previous.digest(p) for p in sources},
        'input_sha256': {path.relative_to(output).as_posix(): previous.digest(path)
                         for path in sorted((output / 'inputs').rglob('*')) if path.is_file()},
    }
    previous.write_json(output / 'protocol_start.json', protocol)
    stage = 'start'
    try:
        episodes, plans, audit_rows = [], [], []
        for scenario in inputs:
            stage = case = f'{scenario.parent.name}__{scenario.stem}'
            local, stored = run_case(output, scenario, case)
            episodes += [{'case': case, **row} for row in local]
            seen = set()
            for row in local:
                if row['planner'] not in seen:
                    seen.add(row['planner'])
                    plans.append({'planner': row['planner'],
                                  'planning_time_ms': row['planning_time_ms']})
            audit_rows += audit(scenario, case, stored)
        stage = 'aggregate'
        planning_p95, summary_rows = {}, []
        for planner in PLANNERS:
            rows = [r for r in episodes if r['planner'] == planner]
            times = [float(r['planning_time_ms']) for r in plans
                     if r['planner'] == planner and r['planning_time_ms'] != '']
            planning_p95[planner] = float(np.quantile(times, .95)) if times else None
            outcome = Counter(r['failure_class'] for r in rows)
            summary_rows.append({
                'planner': planner, 'episodes': len(rows), 'reached': outcome['reached'],
                'collisions': outcome['driving_collision'] + outcome['initial_collision'],
                'timeouts': outcome['timeout'],
                'planning_failures': sum(v for k, v in outcome.items() if k.startswith('planning_')),
                'planning_time_ms_median': float(np.median(times)) if times else None,
                'planning_time_ms_p95': planning_p95[planner]})
        decision = decide(episodes, audit_rows, stratum, planning_p95)
        counts = previous.query_outcomes(episodes)
        query_rows = [{'case': c, 'stratum': stratum[c], **{p: counts[c, p] for p in PLANNERS}}
                      for c in sorted(stratum)]
        previous.write_csv(output / 'summary.csv', summary_rows)
        previous.write_csv(output / 'queries.csv', query_rows)
        previous.write_csv(output / 'acceptance.csv',
                           [{k: v for k, v in r.items() if k != 'path_digest'} for r in audit_rows])
        previous.write_csv(output / 'episodes.csv', episodes)
        previous.write_json(output / 'protocol.json', protocol | {
            'episodes': len(episodes), 'wall_time_s': perf_counter() - started})
        previous.write_json(output / 'decision.json', decision)
    except BaseException as exc:
        previous.write_json(output / 'aborted.json', {
            'stage': stage, 'error': f'{type(exc).__name__}: {exc}',
            'follow_up': FOLLOW_UP['aborted'], 'wall_time_s': perf_counter() - started})
        raise
    return summary_rows, decision


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
