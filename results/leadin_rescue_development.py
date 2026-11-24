"""Development comparison of lead-in rescue variants on already exposed queries.

Pre-registered in docs/LEADIN_RESCUE_DEVELOPMENT.md under research policy v2
(docs/COMMIT_PLAN.md).  Every input here has been exposed by earlier studies, so
this is development selection, never held-out evidence.  The selection rule is
computed by ``decide`` from saved outcomes without any manual step.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

import numpy as np

from raceplan.analyze import main as analyze
from raceplan.common import load_occupancy_map, load_scenario
from raceplan.experiment import main as experiment
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
BASE_PLUGIN = ROOT / 'examples/smoothed_astar_planner.py'
LEADIN_PLUGIN = ROOT / 'examples/leadin_rescue_planner.py'
TURN_AWARE = 'results/analysis/turn_aware_holdout_20261103/inputs'
SMOOTHING = 'results/analysis/smoothing_holdout_20261123/inputs'
INPUTS = (
    [f'{TURN_AWARE}/{split}/{family}/q{query}.yaml'
     for split in ('validation', 'evaluation')
     for family in ('staggered_windows', 'offset_islands') for query in (0, 1)]
    + [f'{SMOOTHING}/{family}/{variant}/q{query}.yaml'
       for family in ('staggered_windows', 'offset_islands', 'slalom_walls')
       for variant in ('a', 'b') for query in (0, 1)]
)
SEEDS = (11, 12, 13)
NOISE = {'initial-position-std-m': 0.02, 'initial-yaw-std-rad': 0.02,
         'steering-std-rad': 0.01, 'speed-measurement-std-mps': 0.02}
CUSTOM = [(BASE_PLUGIN, 'SmoothedLowClearance'), (LEADIN_PLUGIN, 'LeadInRescueK3'),
          (LEADIN_PLUGIN, 'LeadInRescueK6'), (LEADIN_PLUGIN, 'LeadInStraight')]
REFERENCE = 'smoothed_low_clearance'
CANDIDATES = ('leadin_rescue_k3', 'leadin_rescue_k6')
ABLATION = 'leadin_straight'
PLANNERS = ('astar', 'hybrid_astar', REFERENCE, *CANDIDATES, ABLATION)
MIN_REFERENCE_STRATUM = 5
MIN_NET_GAIN = 2
DECISION_RULE = (
    'query reached iff >=2 of 3 seeds reached. Undecidable if the reference reaches fewer '
    f'than {MIN_REFERENCE_STRATUM} queries. A candidate is eligible iff it loses no query '
    'reached by the reference or by A*, and its net query gain over the reference is '
    f'>= {MIN_NET_GAIN}. Among eligible candidates pick highest net gain, then more accepted '
    'queries, then lower planning-time P95, then fewer lead-in attempts (k3 before k6). '
    'The straight-only ablation is never selectable.'
)
FOLLOW_UP = {
    'selected': 'stop; a new held-out under policy v2 needs explicit user approval',
    'none': 'record negative result; do not tune further on these inputs',
    'undecidable': 'record; no selection',
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def read_csv(path: Path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows):
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def git(*args) -> str:
    return subprocess.run(['git', *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout.strip()


def repository_state(prereg_commit: str):
    """Refuse to run from a dirty tracked tree or without the pre-registration commit."""
    if git('status', '--porcelain', '--untracked-files=no'):
        raise ValueError('tracked files are modified; commit before running')
    head = git('rev-parse', 'HEAD')
    prereg = git('rev-parse', '--verify', f'{prereg_commit}^{{commit}}')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', prereg, head], cwd=ROOT).returncode:
        raise ValueError('pre-registration commit is not an ancestor of HEAD')
    return {'run_commit': head, 'tracked_tree_dirty': False, 'prereg_commit': prereg}


def query_outcomes(episodes):
    """{(case, planner): reached seed count} from analysis episode rows."""
    counts = Counter()
    for row in episodes:
        counts[row['case'], row['planner']] += row['failure_class'] == 'reached'
    return counts


def decide(episodes, accepted, planning_p95):
    """Apply the pre-registered query-level rule; returns the decision record."""
    counts = query_outcomes(episodes)
    cases = sorted({row['case'] for row in episodes})
    reached = {(case, planner): counts[case, planner] >= 2
               for case in cases for planner in PLANNERS}
    reference_stratum = [c for c in cases if reached[c, REFERENCE]]
    astar_stratum = [c for c in cases if reached[c, 'astar']]
    rows = []
    for planner in (*CANDIDATES, ABLATION):
        losses_reference = [c for c in reference_stratum if not reached[c, planner]]
        losses_astar = [c for c in astar_stratum if not reached[c, planner]]
        gains = [c for c in cases if reached[c, planner] and not reached[c, REFERENCE]]
        net = len(gains) - len(losses_reference)
        rows.append({
            'planner': planner, 'queries_reached': sum(reached[c, planner] for c in cases),
            'gains_vs_reference': gains, 'losses_vs_reference': losses_reference,
            'losses_vs_astar': losses_astar, 'net_gain_vs_reference': net,
            'accepted_queries': accepted.get(planner, 0),
            'planning_time_ms_p95': planning_p95.get(planner),
            'eligible': (planner in CANDIDATES and not losses_reference and not losses_astar
                         and net >= MIN_NET_GAIN),
        })
    if len(reference_stratum) < MIN_REFERENCE_STRATUM:
        verdict, selected = 'undecidable', None
    else:
        eligible = [r for r in rows if r['eligible']]
        eligible.sort(key=lambda r: (-r['net_gain_vs_reference'], -r['accepted_queries'],
                                     r['planning_time_ms_p95'], CANDIDATES.index(r['planner'])))
        verdict, selected = ('selected', eligible[0]['planner']) if eligible else ('none', None)
    return {'rule': DECISION_RULE, 'queries': len(cases),
            'reference_reached_queries': len(reference_stratum),
            'astar_reached_queries': len(astar_stratum),
            'hybrid_reached_queries': sum(reached[c, 'hybrid_astar'] for c in cases),
            'candidates': rows, 'verdict': verdict, 'selected': selected,
            'follow_up': FOLLOW_UP[verdict]}


def acceptance_audit(scenario_path: Path, case: str, stored_paths):
    """Re-plan each smoother and require the stored path to match pose for pose."""
    scenario = load_scenario(scenario_path)
    grid = load_occupancy_map(scenario.map_path).grid
    rows = []
    for plugin, classname in CUSTOM:
        planner = load_custom_planner(f'{plugin}:{classname}')[0]
        result = planner.plan(grid, scenario.start, scenario.goal, timeout_s=scenario.timeout_s)
        replanned = ([(p.x, p.y, p.yaw) for p in result.path.poses] if result.path else [])
        rows.append({
            'case': case, 'planner': planner.name, 'status': result.status.value,
            'smoothing': result.metadata.get('smoothing'),
            'smoothing_reason': result.metadata.get('smoothing_reason', ''),
            'rescue': result.metadata.get('rescue', ''),
            'lead_in_curvature_per_m': result.metadata.get('lead_in_curvature_per_m', ''),
            'lead_in_length_m': result.metadata.get('lead_in_length_m', ''),
            'smoothed_max_curvature_per_m': result.metadata.get('smoothed_max_curvature_per_m', ''),
            'smoothed_min_footprint_clearance_m': result.metadata.get(
                'smoothed_min_footprint_clearance_m', ''),
            'matches_stored_path': replanned == stored_paths.get(planner.name),
        })
    return rows


def run(output: Path, prereg_commit: str):
    if output.exists():
        raise ValueError('output directory already exists')
    state = repository_state(prereg_commit)
    output.mkdir(parents=True)
    started = perf_counter()
    episodes, plans, accepted_rows = [], [], []
    for name in INPUTS:
        scenario = ROOT / name
        case = '/'.join(Path(name).relative_to('results/analysis').parts).removesuffix('.yaml')
        case = case.replace('/inputs/', '/').replace('/', '__')
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
        local = read_csv(target / 'analysis/episodes.csv')
        episodes += [{'case': case, **row} for row in local]
        seen = set()
        for row in local:
            if row['planner'] not in seen:
                seen.add(row['planner'])
                plans.append({'case': case, 'planner': row['planner'],
                              'planning_time_ms': row['planning_time_ms'],
                              'max_discrete_curvature_per_m': row['max_discrete_curvature_per_m']})
        stored = {}
        for row in read_csv(target / 'comparison_paths.csv'):
            stored.setdefault(row['plan_id'], []).append(
                (float(row['x_m']), float(row['y_m']), float(row['yaw_rad'])))
        accepted_rows += acceptance_audit(scenario, case, stored)

    planning_p95 = {}
    summary_rows = []
    for planner in PLANNERS:
        rows = [r for r in episodes if r['planner'] == planner]
        times = [float(r['planning_time_ms']) for r in plans if r['planner'] == planner]
        planning_p95[planner] = float(np.quantile(times, .95))
        counts = Counter(r['failure_class'] for r in rows)
        summary_rows.append({
            'planner': planner, 'episodes': len(rows), 'reached': counts['reached'],
            'collisions': counts['driving_collision'] + counts['initial_collision'],
            'timeouts': counts['timeout'],
            'planning_failures': sum(v for k, v in counts.items() if k.startswith('planning_')),
            'accepted_queries': sum(a['planner'] == planner and a['smoothing'] == 'accepted'
                                    for a in accepted_rows),
            'planning_time_ms_median': float(np.median(times)),
            'planning_time_ms_p95': planning_p95[planner],
        })
    accepted = {r['planner']: r['accepted_queries'] for r in summary_rows}
    decision = decide(episodes, accepted, planning_p95)
    counts = query_outcomes(episodes)
    query_rows = [{'case': case, **{planner: counts[case, planner] for planner in PLANNERS}}
                  for case in sorted({r['case'] for r in episodes})]

    write_csv(output / 'summary.csv', summary_rows)
    write_csv(output / 'queries.csv', query_rows)
    write_csv(output / 'acceptance.csv', accepted_rows)
    write_csv(output / 'episodes.csv', episodes)
    sources = sorted((ROOT / 'src/raceplan').rglob('*.py')) + [
        BASE_PLUGIN, LEADIN_PLUGIN, Path(__file__).resolve()]
    protocol = {
        'kind': 'development_selection_on_exposed_inputs_not_held_out',
        'policy': 'research policy v2 (docs/COMMIT_PLAN.md, docs/FEATURE_SCOPE.md)',
        **state,
        'uv_lock_sha256': digest(ROOT / 'uv.lock'),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'inputs': list(INPUTS), 'seeds': list(SEEDS), 'noise': NOISE,
        'planners': list(PLANNERS), 'reference': REFERENCE, 'candidates': list(CANDIDATES),
        'ablation': ABLATION, 'decision_rule': DECISION_RULE, 'follow_up': FOLLOW_UP,
        'episodes': len(episodes), 'wall_time_s': perf_counter() - started,
        'acceptance_audit_all_match': all(r['matches_stored_path'] for r in accepted_rows),
        'source_sha256': {rel(path): digest(path) for path in sources},
        'input_sha256': {name: digest(ROOT / name) for name in INPUTS},
    }
    (output / 'protocol.json').write_text(
        json.dumps(protocol, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    (output / 'decision.json').write_text(
        json.dumps(decision, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
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
