"""Compare two saved runs: the same planner, before and after a change (a new planner file version, a new watch run).

Only saved results are read; nothing is planned, simulated or recomputed from trajectories. A case of run A and a case
of run B are the same case when their saved scenario file and map files have the same hashes (the comparison manifest
records them); case ids, paths and names are only shown. Two such cases are compared only when everything else that
decides an episode is the same too (experiment revision, noise, vehicle, tracker, simulation, inflation, collision grid
and the settings of the built-in planners); a user planner's file version is exactly what may differ. A case whose
manifest does not carry this evidence in the expected form is never paired. Episodes are paired by planner name and
simulation seed within compared cases; deltas (B - A) only exist where both episodes reached the goal. Totals over each
whole run, the paired counts and the per-metric sample counts are always given separately, and a change in reached
episodes is only stated over real pairs, so a different denominator is never read as a change.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isfinite
import re

import numpy as np

CONDITION_FIELDS = ('experiment_revision', 'noise', 'noise_model', 'vehicle', 'tracker', 'simulation', 'inflation_radius_m',
                    'collision_grid')
METRICS = {'rmse': ('tracking_rmse_m', 'm'), 'time': ('completion_time_s', 's'),
           'clearance': ('driving_min_sampled_clearance_m', 'm')}
REQUIRED = ('tracking_rmse_m', 'completion_time_s')  # Saved for every reached episode; clearance may be absent.
HASH = re.compile(r'[0-9a-f]{64}')


def case_key(manifest):
    """The saved inputs that make two cases the same case (full hashes)."""
    return (manifest.get('scenario_sha256'), manifest.get('map_yaml_sha256'), manifest.get('map_image_sha256'))


def _key_text(key):
    return sha256(json.dumps(key).encode()).hexdigest()[:12]


def evidence_problem(manifest):
    """Why this manifest cannot say which case it is or under which conditions it ran; None when it can."""
    if not isinstance(manifest, dict):
        return 'no comparison manifest'
    if not all(isinstance(value, str) and HASH.fullmatch(value) for value in case_key(manifest)):
        return 'scenario or map file hashes are missing'
    if type(manifest.get('experiment_revision')) is not int:
        return 'experiment revision is missing'
    if not all(isinstance(manifest.get(field), dict) for field in ('noise', 'vehicle', 'tracker', 'simulation', 'planners')):
        return 'noise, vehicle, tracker, simulation or planner settings are missing'
    if not all(isinstance(manifest.get(field), str) and manifest[field] for field in ('noise_model', 'collision_grid')):
        return 'noise model or collision grid description is missing'
    if not isinstance(manifest.get('inflation_radius_m'), (int, float)) or isinstance(manifest.get('inflation_radius_m'), bool):
        return 'inflation radius is missing'
    seeds = manifest.get('simulation_seeds')
    if (not isinstance(seeds, list) or not seeds or any(type(seed) is not int for seed in seeds)
            or len(set(seeds)) != len(seeds)):
        return 'simulation seeds are missing or repeated'
    if not isinstance(manifest.get('source_sha256'), dict) or not manifest['source_sha256'] or not all(
            isinstance(manifest.get(field), str) and manifest[field] for field in ('python', 'numpy')):
        return 'engine source or runtime record is missing'
    return None


def _custom(manifest):
    sources = manifest.get('custom_planner_sources')
    return sources if isinstance(sources, dict) else {}


def condition(manifest):
    """Everything besides the user planners' own code that decides an episode of this case."""
    planners = manifest.get('planners') if isinstance(manifest.get('planners'), dict) else {}
    builtin = {name: planners[name] for name in sorted(planners) if name not in _custom(manifest)}
    return {**{field: manifest.get(field) for field in CONDITION_FIELDS}, 'builtin_planners': builtin}


def _engine_files(manifest):
    """RacePlan source hashes outside the explorer itself (gui/ only shows results, it does not decide them)."""
    files = manifest.get('source_sha256')
    return {name: value for name, value in files.items() if not name.replace('\\', '/').startswith('gui/')} \
        if isinstance(files, dict) else None


def environment(manifest):
    """The engine and runtime a case ran on: RacePlan engine sources, Python and NumPy versions."""
    return {'engine': _engine_files(manifest), 'python': manifest.get('python'), 'numpy': manifest.get('numpy')}


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def versions(manifests):
    """User planner versions a run really loaded: {planner: [{'sha256', 'class', 'cases'}]}; more than one entry for
    a planner (another file content or another class) means its cases did not all run the same planner."""
    found = defaultdict(dict)
    for case_id, manifest in manifests:
        for name, source in _custom(manifest).items():
            if isinstance(source, dict):
                key = (source.get('sha256'), source.get('class'))
                entry = found[name].setdefault(key, {'sha256': key[0], 'class': key[1], 'cases': []})
                entry['cases'].append(case_id)
    return {name: list(entries.values()) for name, entries in found.items()}


def run_meta(manifests, total_cases, finished_at, watch):
    """What the run list shows about a run, and the fingerprint that finds earlier runs of the same conditions.
    manifests: [(case_id, manifest)] of the cases that completed. The fingerprint exists only when every case
    completed with full evidence: it covers the cases (input hashes), their conditions, seeds, planner names and the
    engine and runtime, so a run it matches differs at most in the user planners' code."""
    usable = [(case_id, manifest) for case_id, manifest in manifests if evidence_problem(manifest) is None]
    seeds = sorted({seed for _, manifest in usable for seed in manifest['simulation_seeds']})
    noise = [any(isinstance(value, (int, float)) and value > 0 for value in manifest['noise'].values()) for _, manifest in usable]
    planners = sorted({name for _, manifest in usable for name in manifest['planners']})
    found = versions(usable)
    per_case = sorted([_key_text(case_key(manifest)), _digest(condition(manifest)), sorted(manifest['simulation_seeds']),
                       sorted(manifest['planners']), _digest(environment(manifest))] for _, manifest in usable)
    keys = [case_key(manifest) for _, manifest in usable]
    # A run that repeats the same saved inputs in two cases cannot be paired case by case (they would be ambiguous).
    complete = bool(usable) and len(usable) == len(manifests) == total_cases and len(set(keys)) == len(keys)
    return {'cases_total': total_cases, 'cases_complete': len(manifests), 'cases_without_evidence': len(manifests) - len(usable),
            'seeds': seeds, 'noise': 'unknown' if not noise else 'some' if all(noise) else 'none' if not any(noise) else 'mixed',
            'planners': planners, 'versions': found, 'mixed_versions': sorted(name for name, items in found.items() if len(items) > 1),
            'finished_at': finished_at, 'watch': watch, 'fingerprint': _digest(per_case) if complete else None}


def _number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _rows(case):
    """(planner, seed) -> saved episode row; a repeated pair is an error, never a silent pick."""
    rows = {}
    for row in case['episodes']:
        key = (row['planner'], str(row['simulation_seed']))
        if key in rows:
            raise ValueError(f'case {case["id"]}: {key[0]} seed {key[1]} appears twice in its saved episodes')
        if row['failure_class'] == 'reached':
            for field in REQUIRED:
                if _number(row.get(field)) is None:
                    raise ValueError(f'case {case["id"]}: {key[0]} seed {key[1]} reached the goal but {field} is '
                                     f'{row.get(field)!r}, not a finite number')
        rows[key] = row
    return rows


def _median(values):
    return float(np.median(values)) if values else None


def _match_cases(a, b, issues):
    """Case matching by saved input hashes; returns (case entries, compared (left, right, seeds), problems)."""
    by_key, unusable = {}, []
    for side, run in (('a', a), ('b', b)):
        groups = defaultdict(list)
        for case in run['cases']:
            problem = evidence_problem(case['manifest'])
            if problem:
                unusable.append({'key': None, 'case_a': [case['id']] if side == 'a' else [], 'case_b': [case['id']] if side == 'b' else [],
                                 'status': 'no_evidence', 'reason': problem})
            else:
                groups[case_key(case['manifest'])].append(case)
        by_key[side] = groups
    cases, compared, engine, runtime = list(unusable), [], set(), set()
    for key in sorted(set(by_key['a']) | set(by_key['b']), key=_key_text):
        left, right = by_key['a'].get(key, []), by_key['b'].get(key, [])
        entry = {'key': _key_text(key), 'case_a': [case['id'] for case in left], 'case_b': [case['id'] for case in right]}
        if len(left) > 1 or len(right) > 1:
            entry.update(status='ambiguous', reason='the same saved inputs appear in more than one case of a run')
        elif not left or not right:
            entry.update(status='a_only' if left else 'b_only', reason='no case with the same scenario and map files')
        else:
            first, second = left[0]['manifest'], right[0]['manifest']
            changed = [field for field, value in condition(first).items() if condition(second).get(field) != value]
            seeds_a, seeds_b = [str(seed) for seed in first['simulation_seeds']], [str(seed) for seed in second['simulation_seeds']]
            common = [seed for seed in seeds_a if seed in seeds_b]
            if changed:
                entry.update(status='condition_changed', reason='different ' + ', '.join(changed), changed=changed)
            elif not common:
                entry.update(status='no_common_seed', reason='no simulation seed in common')
            else:
                entry.update(status='compared', seeds=common, seeds_a_only=[s for s in seeds_a if s not in seeds_b],
                             seeds_b_only=[s for s in seeds_b if s not in seeds_a])
                compared.append((left[0], right[0], common))
            for name, source in _custom(first).items():
                other = _custom(second).get(name)
                if isinstance(source, dict) and isinstance(other, dict) and source.get('class') != other.get('class'):
                    issues.append(f'{name}: class {source.get("class")} in A, {other.get("class")} in B')
            left_env, right_env = environment(first), environment(second)
            if left_env['engine'] != right_env['engine']:
                engine |= ({'(source record missing)'} if not left_env['engine'] or not right_env['engine'] else
                           {name for name in set(left_env['engine']) | set(right_env['engine'])
                            if left_env['engine'].get(name) != right_env['engine'].get(name)})
            runtime |= {f'{part} {left_env[part]} → {right_env[part]}' for part in ('python', 'numpy') if left_env[part] != right_env[part]}
        cases.append(entry)
    # The same case id on both sides with other input hashes: the inputs of that case changed (not paired).
    only = {side: {case_id for entry in cases if entry['status'] == f'{side}_only' for case_id in entry[f'case_{side}']}
            for side in ('a', 'b')}
    for case_id in sorted(only['a'] & only['b']):
        issues.append(f'case {case_id}: its scenario or map files changed between the runs, so it is not paired')
    if engine:
        issues.append('RacePlan engine files differ between the runs, so not only the planner changed: '
                      + ', '.join(sorted(engine)[:6]) + (' …' if len(engine) > 6 else ''))
    if runtime:
        issues.append('the runs used another runtime: ' + ', '.join(sorted(runtime)))
    if any(entry.get('seeds_a_only') or entry.get('seeds_b_only') for entry in cases):
        issues.append('some seeds were run in only one of the runs; only the seeds both ran are paired')
    return cases, compared


def compare(a, b):
    """a, b: {'id', 'complete', 'cases': [{'id', 'manifest', 'episodes'}]} of the completed cases of each run (one
    loaded snapshot each). Returns case matching, warnings and, per planner, whole-run totals, paired counts, the change
    in reached episodes over the pairs and deltas B - A."""
    issues = []
    cases, compared = _match_cases(a, b, issues)
    rows = {side: {case['id']: _rows(case) for case in run['cases']} for side, run in (('a', a), ('b', b))}
    names = {side: {key[0] for case_rows in rows[side].values() for key in case_rows} for side in rows}
    planners, total_pairs = [], 0
    for name in sorted(names['a'] | names['b']):
        totals = {}
        for side in ('a', 'b'):
            mine = [row for case_rows in rows[side].values() for (planner, _), row in case_rows.items() if planner == name]
            totals[side] = {'recorded': len(mine), 'reached': sum(row['failure_class'] == 'reached' for row in mine)}
        counts, deltas, pairs, excluded = Counter(), {metric: [] for metric in METRICS}, [], Counter()
        for left, right, seeds in compared:
            in_left = any(planner == name for planner, _ in rows['a'][left['id']])
            in_right = any(planner == name for planner, _ in rows['b'][right['id']])
            if not in_left and not in_right:
                continue  # Neither case ran this planner: nothing missing, nothing to pair.
            for seed in seeds:
                first, second = rows['a'][left['id']].get((name, seed)), rows['b'][right['id']].get((name, seed))
                if first is None or second is None:
                    counts['missing'] += 1
                    continue
                ok_a, ok_b = first['failure_class'] == 'reached', second['failure_class'] == 'reached'
                kind = 'both' if ok_a and ok_b else 'a_only' if ok_a else 'b_only' if ok_b else 'neither'
                counts[kind] += 1
                pair = {'case_a': left['id'], 'case_b': right['id'], 'seed': seed, 'kind': kind,
                        'outcome_a': first['failure_class'], 'outcome_b': second['failure_class'], 'deltas': {}}
                for metric, (field, _) in METRICS.items():
                    before, after = _number(first.get(field)), _number(second.get(field))
                    pair[metric] = [before, after]
                    if kind != 'both':
                        continue
                    if before is None or after is None:
                        excluded[metric] += 1
                        continue
                    pair['deltas'][metric] = after - before
                    deltas[metric].append(after - before)
                pairs.append(pair)
        paired = sum(counts[kind] for kind in ('both', 'a_only', 'b_only', 'neither'))
        total_pairs += paired
        planners.append({'planner': name, 'in_a': name in names['a'], 'in_b': name in names['b'], 'totals': totals,
                         'pairs': {kind: counts[kind] for kind in ('both', 'a_only', 'b_only', 'neither', 'missing')},
                         'paired': paired, 'paired_change': counts['b_only'] - counts['a_only'] if paired else None,
                         'deltas': {metric: {'n': len(values), 'median': _median(values), 'excluded': excluded[metric]}
                                    for metric, values in deltas.items()},
                         'rows': pairs})
    only = sorted(names['a'] ^ names['b'])
    if only:
        issues.append('planners in only one run: ' + ', '.join(only))
    statuses = Counter(entry['status'] for entry in cases)
    full = (total_pairs and statuses['compared'] == len(cases) and not only and a.get('complete', True) and b.get('complete', True)
            and not any(entry.get('seeds_a_only') or entry.get('seeds_b_only') for entry in cases)
            and not any(item['pairs']['missing'] for item in planners))
    return {'scope': 'none' if not total_pairs else 'full' if full else 'overlap', 'cases': cases,
            'case_counts': dict(statuses), 'issues': list(dict.fromkeys(issues)), 'planners': planners,
            'metrics': {metric: unit for metric, (_, unit) in METRICS.items()}}
