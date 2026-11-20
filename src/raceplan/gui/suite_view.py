"""All cases of a suite at once: totals per planner, the planner x case reach matrix, and comparisons pooled over cases.

Totals use the definitions raceplan.suite writes into summary.csv and case_summary.csv (that module is part of the
recorded research sources and is not imported for this): reached = failure_class 'reached', collisions = saved
collision flag, timeouts = simulation_status 'timeout', planning failures = planning_status other than 'success'
(planning errors are a part of them), success medians over the reached rows of all included cases together (never a
median of case medians). Only cases whose saved results were validated are counted; the coverage says which.
Comparisons apply the single-case rules to each case first and then pool, so seeds of different cases never pair.
Nothing here plans or simulates.
"""
from __future__ import annotations

from collections import Counter
from math import isclose, isfinite

import numpy as np

from raceplan.gui import analysis

CHECKED_FIELDS = ('episodes_recorded', 'reached', 'collisions', 'timeouts', 'planning_failures', 'planning_errors',
                  'success_median_tracking_rmse_m', 'success_median_completion_time_s')
COUNTS = ('records', 'plotted', 'not_reached', 'no_value', 'log_axis')


def _median(values):
    return float(np.median(values)) if values else None


def summarize(rows):
    """Totals of one group of saved episode rows (text values as stored in episodes.csv, already checked by totals)."""
    reached = [row for row in rows if row['failure_class'] == 'reached']
    return {'episodes_recorded': len(rows), 'reached': len(reached),
            'collisions': sum(row['collision'] == 'True' for row in rows),
            'timeouts': sum(row['simulation_status'] == 'timeout' for row in rows),
            'planning_failures': sum(row['planning_status'] != 'success' for row in rows),
            'planning_errors': sum(row['planning_status'] == 'planning_error' for row in rows),
            'success_median_tracking_rmse_m': _median([float(row['tracking_rmse_m']) for row in reached]),
            'success_median_completion_time_s': _median([float(row['completion_time_s']) for row in reached]),
            'outcomes': dict(Counter(row['failure_class'] for row in rows))}


def _check_reached(case_id, row):
    """A reached episode must carry a finite value for each success median; a bad sample is an error, never dropped."""
    for field in ('tracking_rmse_m', 'completion_time_s'):
        text = row.get(field)
        try:
            value = float(text)
        except (TypeError, ValueError):
            value = None
        if value is None or not isfinite(value):
            raise ValueError(f'case {case_id}: {row.get("planner")} seed {row.get("simulation_seed")} reached the goal '
                             f'but {field} is {text!r}, not a finite number')


def planner_order(cases):
    order = []
    for case in cases:
        order += [name for name in case['planners'] if name not in order]
    return order


def totals(cases):
    """cases: [{'id', 'planners', 'rows'}] of included cases. Returns (per-planner totals, matrix[case][planner])."""
    for case in cases:
        for row in case['rows']:
            if row['failure_class'] == 'reached':
                _check_reached(case['id'], row)
    order = planner_order(cases)
    leaderboard = [{'planner': name, **summarize([row for case in cases for row in case['rows'] if row['planner'] == name])}
                   for name in order]
    matrix = {case['id']: {name: summarize([row for row in case['rows'] if row['planner'] == name])
                           for name in case['planners']} for case in cases}
    return leaderboard, matrix


def _saved_number(text):
    return None if text in (None, '') else float(text)


def check_saved(leaderboard, matrix, summary_rows, case_rows):
    """Compare the totals with the suite's own summary.csv (case_id ALL) and case_summary.csv; every difference is
    listed by file, row and field. Missing, extra (also for cases not included) and repeated rows and missing
    columns are differences too; an empty cell only matches a value that is absent (no reached episode)."""
    differences = []

    def note(source, key, field, saved, computed):
        differences.append({'file': source, 'row': key, 'field': field, 'saved': saved, 'computed': computed})

    def compare(source, key, computed, saved):
        if saved is None:
            note(source, key, None, None, 'row')
            return
        for field in CHECKED_FIELDS:
            if field not in saved:
                note(source, key, field, 'no column', computed[field])
                continue
            mine = computed[field]
            try:
                theirs = _saved_number(saved[field])
            except (TypeError, ValueError):
                theirs = saved[field]
            same = (mine is None and theirs is None) or (
                mine is not None and isinstance(theirs, float) and isclose(float(mine), theirs, rel_tol=1e-12, abs_tol=1e-12))
            if not same:
                note(source, key, field, saved[field], mine)

    def index(source, rows, key):
        found = {}
        for row in rows:
            name = key(row)
            if name in found:
                note(source, ' / '.join(map(str, name)) if isinstance(name, tuple) else name, None, 'repeated row', None)
            found[name] = row
        return found

    for row in summary_rows:
        if row.get('case_id') != 'ALL':
            note('summary.csv', row.get('planner'), 'case_id', row.get('case_id'), 'ALL')
    saved_all = index('summary.csv', [row for row in summary_rows if row.get('case_id') == 'ALL'], lambda row: row.get('planner'))
    for entry in leaderboard:
        compare('summary.csv', entry['planner'], entry, saved_all.pop(entry['planner'], None))
    for name in saved_all:
        note('summary.csv', name, None, 'row', None)
    saved_cases = index('case_summary.csv', case_rows, lambda row: (row.get('case_id'), row.get('planner')))
    for case_id, planners in matrix.items():
        for name, computed in planners.items():
            compare('case_summary.csv', f'{case_id} / {name}', computed, saved_cases.pop((case_id, name), None))
    for case_id, name in saved_cases:
        note('case_summary.csv', f'{case_id} / {name}', None, 'row', None)
    return differences


def pooled_delta(cases, metric='rmse', planners=None, seeds=None, outcomes=None):
    """Paired delta of every case with the single-case rules, pooled into lanes per (planner, baseline)."""
    if metric not in analysis.DELTA_METRICS:
        raise analysis.BadQuery(f'unknown delta metric: {metric}')
    _, _, unit, better = analysis.DELTA_METRICS[metric]
    result = {'metric': metric, 'scope': 'all', 'unit': unit, 'better': better, 'lanes': [], 'baselines': [],
              'candidate': 0, 'plotted': 0, 'excluded': dict.fromkeys(analysis.EXCLUSION_REASONS, 0),
              'excluded_pairs': [], 'cases_without_baseline': []}
    lanes = {}
    for case in cases:
        part = analysis.paired_delta(case, metric, planners, seeds, outcomes)
        if part['baseline'] is None:
            result['cases_without_baseline'].append(case['id'])
            continue
        if part['baseline'] not in result['baselines']:
            result['baselines'].append(part['baseline'])
        for lane in part['lanes']:
            pooled = lanes.setdefault((lane['planner'], part['baseline']), {
                'planner': lane['planner'], 'baseline': part['baseline'], 'points': [], 'candidate': 0, 'median': None,
                'excluded': dict.fromkeys(analysis.EXCLUSION_REASONS, 0)})
            pooled['points'] += [{**point, 'case': case['id']} for point in lane['points']]
            pooled['candidate'] += lane['candidate']
            for reason, count in lane['excluded'].items():
                pooled['excluded'][reason] += count
        result['candidate'] += part['candidate']
        result['plotted'] += part['plotted']
        for reason, count in part['excluded'].items():
            result['excluded'][reason] += count
        result['excluded_pairs'] += [{**pair, 'case': case['id']} for pair in part['excluded_pairs']]
    for lane in lanes.values():
        if lane['points']:
            lane['median'] = float(np.median([point['delta'] for point in lane['points']]))
        result['lanes'].append(lane)
    result['baseline'] = result['baselines'][0] if len(result['baselines']) == 1 else None
    return result


def pooled_scatter(cases, x='reported', planners=None, seeds=None, outcomes=None):
    """Scatter of every case's reached episodes; counts are summed and every point and exclusion names its case."""
    if x not in analysis.SCATTER_X:
        raise analysis.BadQuery(f'unknown scatter x: {x}')
    result = {'x': x, 'x_field': analysis.SCATTER_X[x], 'y_field': 'tracking_rmse_m', 'scope': 'all',
              **dict.fromkeys(COUNTS, 0), 'points': [], 'excluded': []}
    for case in cases:
        part = analysis.scatter(case, x, planners, seeds, outcomes)
        for key in COUNTS:
            result[key] += part[key]
        result['points'] += [{**point, 'case': case['id']} for point in part['points']]
        result['excluded'] += [{**item, 'case': case['id']} for item in part['excluded']]
    return result


def planner_versions(provenance, manifests):
    """Did every case run the user planner files the suite recorded before it started? raceplan.suite hashes each file
    once (provenance.json input_sha256) and each case's workflow records the bytes it really loaded
    (comparison_manifest.json custom_planner_sources). A file saved in between makes them differ; the case's numbers
    then belong to another version than the suite's record. manifests: [(case_id, manifest)] of included cases."""
    recorded = provenance.get('input_sha256') if isinstance(provenance, dict) else None
    recorded = recorded if isinstance(recorded, dict) else {}  # An unusual record is checked as "nothing recorded".
    mismatches, checked = [], 0
    for case_id, manifest in manifests:
        sources = manifest.get('custom_planner_sources') if isinstance(manifest, dict) else None
        for name, source in (sources.items() if isinstance(sources, dict) else ()):
            if not isinstance(source, dict):
                continue
            expected = recorded.get(source.get('path'))
            checked += 1
            if expected is None or expected != source.get('sha256'):
                mismatches.append({'case': case_id, 'planner': name, 'path': source.get('path'),
                                   'recorded': str(expected or '')[:12], 'ran': str(source.get('sha256', ''))[:12]})
    return {'checked': checked, 'mismatches': mismatches}
