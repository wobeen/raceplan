"""Paired delta and scatter aggregation over saved episodes; never plans or simulates."""
from __future__ import annotations

from statistics import median

DELTA_METRICS = {
    'rmse': ('delta_tracking_rmse_m', 'both_reached', 'm', 'lower'),
    'time': ('delta_completion_time_s', 'both_reached', 's', 'lower'),
    'clearance': ('delta_driving_min_sampled_clearance_m', 'both_driven', 'm', 'higher'),
}
SCATTER_X = {'reported': 'planning_time_ms', 'runner': 'runner_planning_time_ms'}
EXCLUSION_REASONS = ('missing_pair', 'filtered_outcome', 'condition', 'no_delta')
REACHED = 'reached'


class BadQuery(ValueError):
    """The requested metric or option is not supported."""


def _selection(case, planners, seeds, outcomes):
    return (set(case['planners']) if planners is None else set(planners),
            set(case['seeds']) if seeds is None else set(seeds),
            None if outcomes is None else set(outcomes))


def paired_delta(case, metric='rmse', planners=None, seeds=None, outcomes=None):
    """Plot every compared planner x seed pair once and count each excluded pair under one reason.

    The baseline is the saved one; it is looked up even when it is not selected. The outcome filter
    applies to the compared planner's episode. Pairs without a saved row are never drawn at zero."""
    if metric not in DELTA_METRICS:
        raise BadQuery(f'unknown delta metric: {metric}')
    field, condition, unit, better = DELTA_METRICS[metric]
    baseline = case['baseline']
    result = {'metric': metric, 'unit': unit, 'better': better, 'baseline': baseline, 'lanes': [],
              'candidate': 0, 'plotted': 0, 'excluded': dict.fromkeys(EXCLUSION_REASONS, 0)}
    if baseline is None:
        return result
    chosen_planners, chosen_seeds, chosen_outcomes = _selection(case, planners, seeds, outcomes)
    pairs = {(pair['planner'], pair['simulation_seed']): pair for pair in case['pairs']}
    episodes = {(row['planner'], row['simulation_seed']): row for row in case['episodes']}
    for planner in case['planners']:
        if planner == baseline or planner not in chosen_planners:
            continue
        lane = {'planner': planner, 'points': [], 'candidate': 0, 'median': None,
                'excluded': dict.fromkeys(EXCLUSION_REASONS, 0)}
        for seed in case['seeds']:
            if seed not in chosen_seeds:
                continue
            lane['candidate'] += 1
            pair, episode = pairs.get((planner, seed)), episodes.get((planner, seed))
            if pair is None or episode is None:
                reason = 'missing_pair'
            elif chosen_outcomes is not None and episode['failure_class'] not in chosen_outcomes:
                reason = 'filtered_outcome'
            elif not pair[condition]:
                reason = 'condition'
            elif pair[field] is None:
                reason = 'no_delta'
            else:
                reason = None
                lane['points'].append({'seed': seed, 'delta': pair[field], 'episode_id': episode['episode_id'],
                                       'outcome': episode['failure_class']})
            if reason:
                lane['excluded'][reason] += 1
        if lane['points']:
            lane['median'] = median(point['delta'] for point in lane['points'])
        result['lanes'].append(lane)
        result['candidate'] += lane['candidate']
        result['plotted'] += len(lane['points'])
        for reason, count in lane['excluded'].items():
            result['excluded'][reason] += count
    return result


def scatter(case, x='reported', planners=None, seeds=None, outcomes=None):
    """Plot reached episodes as planning time x tracking RMSE; every other filtered record is counted."""
    if x not in SCATTER_X:
        raise BadQuery(f'unknown scatter x: {x}')
    field = SCATTER_X[x]
    chosen_planners, chosen_seeds, chosen_outcomes = _selection(case, planners, seeds, outcomes)
    result = {'x': x, 'x_field': field, 'y_field': 'tracking_rmse_m', 'records': 0, 'plotted': 0,
              'not_reached': 0, 'no_value': 0, 'log_axis': 0, 'points': []}
    for row in case['episodes']:
        if (row['planner'] not in chosen_planners or row['simulation_seed'] not in chosen_seeds
                or (chosen_outcomes is not None and row['failure_class'] not in chosen_outcomes)):
            continue
        result['records'] += 1
        if row['failure_class'] != REACHED:
            result['not_reached'] += 1
        elif row[field] is None or row['tracking_rmse_m'] is None:
            result['no_value'] += 1
        elif row[field] <= 0:
            result['log_axis'] += 1
        else:
            result['plotted'] += 1
            result['points'].append({'planner': row['planner'], 'seed': row['simulation_seed'],
                                     'plan_id': row['plan_id'], 'episode_id': row['episode_id'],
                                     'x': row[field], 'y': row['tracking_rmse_m']})
    return result
