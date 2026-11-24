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
from math import ceil
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
MIN_REJECTED = 4
MIN_GAIN = 2
MIN_GAIN_FRACTION = 0.25
MIN_REGRESSION_STRATUM = 2
DECISION_RULE = (
    'query reached iff >=2 of 3 seeds reached. Any acceptance-audit mismatch invalidates the '
    'run. Candidates can differ from the reference only on queries whose reference '
    'post-processing was rejected (raw A* fallback), so the effect denominator is that '
    f'rejected set; undecidable if it has fewer than {MIN_REJECTED} queries. A candidate is '
    'eligible iff it loses no query reached by the reference or by A* and its net query gain '
    f'over the reference is >= max({MIN_GAIN}, ceil({MIN_GAIN_FRACTION} x rejected queries)). '
    'No-regression evidence is "tested" only if at least '
    f'{MIN_REGRESSION_STRATUM} rejected queries were reached by the reference fallback; '
    'otherwise a selection is labelled "selected on gain only, regression untestable". Among '
    'eligible candidates pick highest net gain, then more accepted queries, then lower '
    'planning-time P95, then fewer lead-in attempts (k3 before k6). The straight-only '
    'ablation is never selectable.'
)
FOLLOW_UP = {
    'selected': 'stop; a new held-out under policy v2 needs explicit user approval and must '
                'include rejected queries that the reference fallback reaches',
    'none': 'record negative result; do not tune further on these inputs',
    'undecidable': 'record; no selection; no rerun in this step',
    'invalid_audit': 'record only; no rerun in this step; nondeterminism is a new step',
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


def decide(episodes, audit_rows, planning_p95):
    """Apply the pre-registered query-level rule; returns the decision record."""
    counts = query_outcomes(episodes)
    cases = sorted({row['case'] for row in episodes})
    reached = {(case, planner): counts[case, planner] >= 2
               for case in cases for planner in PLANNERS}
    audit = {(row['case'], row['planner']): row for row in audit_rows}
    rejected = [c for c in cases if audit.get((c, REFERENCE), {}).get('smoothing') == 'rejected']
    regression_stratum = [c for c in rejected if reached[c, REFERENCE]]
    reference_reached = [c for c in cases if reached[c, REFERENCE]]
    astar_reached = [c for c in cases if reached[c, 'astar']]
    required_gain = max(MIN_GAIN, ceil(MIN_GAIN_FRACTION * len(rejected)))
    audit_ok = bool(audit_rows) and all(row['matches_stored_path'] for row in audit_rows)
    decidable = audit_ok and len(rejected) >= MIN_REJECTED
    rows = []
    for planner in (*CANDIDATES, ABLATION):
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
                         and not losses_astar and net >= required_gain),
        })
    if not audit_ok:
        verdict, selected = 'invalid_audit', None
    elif not decidable:
        verdict, selected = 'undecidable', None
    else:
        eligible = [r for r in rows if r['eligible']]
        eligible.sort(key=lambda r: (-r['net_gain_vs_reference'], -r['accepted_queries'],
                                     r['planning_time_ms_p95'] if r['planning_time_ms_p95']
                                     is not None else float('inf'),
                                     CANDIDATES.index(r['planner'])))
        verdict, selected = ('selected', eligible[0]['planner']) if eligible else ('none', None)
    evidence = ('tested' if len(regression_stratum) >= MIN_REGRESSION_STRATUM
                else 'untestable')
    return {'rule': DECISION_RULE, 'queries': len(cases),
            'reference_rejected_queries': rejected,
            'rejected_and_fallback_reached': regression_stratum,
            'required_net_gain': required_gain, 'no_regression_evidence': evidence,
            'reference_reached_queries': len(reference_reached),
            'astar_reached_queries': len(astar_reached),
            'hybrid_reached_queries': sum(reached[c, 'hybrid_astar'] for c in cases),
            'audit_all_match': audit_ok,
            'audit_mismatches': [f"{row['case']}/{row['planner']}" for row in audit_rows
                                 if not row['matches_stored_path']],
            'rescue_timeouts': dict(Counter(row['planner'] for row in audit_rows
                                            if row.get('rescue') == 'timeout')),
            'candidates': rows, 'verdict': verdict,
            'selected': selected,
            'selection_label': ('selected on gain only, regression untestable'
                                if verdict == 'selected' and evidence == 'untestable' else ''),
            'follow_up': FOLLOW_UP[verdict]}


def acceptance_audit(scenario_path: Path, case: str, stored_paths):
    """Re-plan each smoother and require the stored path to match pose for pose."""
    scenario = load_scenario(scenario_path)
    grid = load_occupancy_map(scenario.map_path).grid
    rows = []
    for plugin, classname in CUSTOM:
        planner = load_custom_planner(f'{plugin}:{classname}')[0]
        try:
            result = planner.plan(grid, scenario.start, scenario.goal,
                                  timeout_s=scenario.timeout_s)
        except Exception as exc:  # the experiment records these as planning_error rows
            rows.append({'case': case, 'planner': planner.name, 'status': 'planning_error',
                         'smoothing': '', 'smoothing_reason': type(exc).__name__, 'rescue': '',
                         'lead_in_curvature_per_m': '', 'lead_in_length_m': '',
                         'smoothed_max_curvature_per_m': '',
                         'smoothed_min_footprint_clearance_m': '',
                         'matches_stored_path': stored_paths.get(planner.name, []) == []})
            continue
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
            'matches_stored_path': replanned == stored_paths.get(planner.name, []),
        })
    return rows


def case_name(name: str) -> str:
    stem = name.replace('\\', '/').removeprefix('results/analysis/').removesuffix('.yaml')
    return stem.replace('/inputs/', '/').replace(':', '').replace('/', '__')


def input_hashes(inputs):
    """Scenario YAML plus the map YAML and image each scenario reads."""
    hashes = {}
    for name in inputs:
        scenario = ROOT / name
        hashes[name] = digest(scenario)
        metadata = load_occupancy_map(load_scenario(scenario).map_path)
        for path in (metadata.yaml_path, metadata.image_path):
            key = rel(path) if Path(path).resolve().is_relative_to(ROOT) else str(path)
            hashes[key] = digest(Path(path))
    return hashes


def write_json(path: Path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
                    encoding='utf-8')


def run(output: Path, prereg_commit: str, inputs=INPUTS):
    if output.exists():
        raise ValueError('output directory already exists')
    state = repository_state(prereg_commit)
    output.mkdir(parents=True)
    sources = sorted((ROOT / 'src/raceplan').rglob('*.py')) + [
        BASE_PLUGIN, LEADIN_PLUGIN, Path(__file__).resolve()]
    protocol = {
        'kind': 'development_selection_on_exposed_inputs_not_held_out',
        'policy': 'research policy v2 (docs/COMMIT_PLAN.md, docs/FEATURE_SCOPE.md)',
        **state,
        'uv_lock_sha256': digest(ROOT / 'uv.lock'),
        'python': sys.version.split()[0], 'platform': platform.platform(),
        'raceplan_import_path': Path(sys.modules['raceplan'].__file__).resolve().parent.as_posix(),
        'inputs': list(inputs), 'seeds': list(SEEDS), 'noise': NOISE,
        'planners': list(PLANNERS), 'reference': REFERENCE, 'candidates': list(CANDIDATES),
        'ablation': ABLATION, 'decision_rule': DECISION_RULE, 'follow_up': FOLLOW_UP,
        'source_sha256': {rel(path): digest(path) for path in sources},
        'input_sha256': input_hashes(inputs),
    }
    # Written before any planning so an interrupted run still documents what was attempted.
    write_json(output / 'protocol_start.json', protocol)
    started = perf_counter()
    episodes, plans, audit_rows = [], [], []
    for name in inputs:
        scenario = ROOT / name
        case = case_name(name)
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
                              'planning_time_ms': row['planning_time_ms']})
        stored = {}
        for row in read_csv(target / 'comparison_paths.csv'):
            stored.setdefault(row['plan_id'], []).append(
                (float(row['x_m']), float(row['y_m']), float(row['yaw_rad'])))
        audit_rows += acceptance_audit(scenario, case, stored)

    planning_p95 = {}
    summary_rows = []
    for planner in PLANNERS:
        rows = [r for r in episodes if r['planner'] == planner]
        # Planning errors have no reported time; they are counted as failures, not timed.
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
    counts = query_outcomes(episodes)
    query_rows = [{'case': case, **{planner: counts[case, planner] for planner in PLANNERS}}
                  for case in sorted({r['case'] for r in episodes})]

    write_csv(output / 'summary.csv', summary_rows)
    write_csv(output / 'queries.csv', query_rows)
    write_csv(output / 'acceptance.csv', audit_rows)
    write_csv(output / 'episodes.csv', episodes)
    write_json(output / 'protocol.json', protocol | {
        'episodes': len(episodes), 'wall_time_s': perf_counter() - started,
        'acceptance_audit_all_match': decision['audit_all_match']})
    write_json(output / 'decision.json', decision)
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
