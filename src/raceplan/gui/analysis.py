"""Paired delta, scatter and side-by-side replay timelines over saved episodes; never plans or simulates."""
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


def trace_valid(trace):
    """Saved samples are playable only with t/x/y of equal length, no missing value and times rising from 0 s or later."""
    times = trace['t']
    return (bool(times) and len(trace['x']) == len(trace['y']) == len(times)
            and all(value is not None for key in ('t', 'x', 'y') for value in trace[key])
            and times[0] >= 0 and all(later >= earlier for earlier, later in zip(times, times[1:])))


def _replay_side(episodes, traces, planner, seed):
    """Describe one slot's saved samples as state events; never invent motion before or after them."""
    row = episodes.get((planner, seed))
    side = {'planner': planner, 'episode_id': None, 'plan_id': None, 'outcome': None, 'samples': 0,
            'start_s': None, 'end_s': None, 'reason': None, 'events': [[0.0, 'no_record']]}
    if row is None:
        side['reason'] = 'missing_episode'
        return side
    side.update(episode_id=row['episode_id'], plan_id=row['plan_id'] or None, outcome=row['failure_class'])
    trace = traces.get(row['episode_id'])
    times = trace['t'] if trace else []
    side['samples'] = len(times)
    if not times:
        side['reason'] = 'no_samples'
        return side
    if not trace_valid(trace):
        side['reason'] = 'invalid_samples'
        return side
    start, end = times[0], times[-1]
    events = [[0.0, 'waiting']] if start > 0 else []
    if end > start:
        events.append([start, 'driving'])
    events.append([end, 'ended'])
    side.update(start_s=start, end_s=end, events=events)
    return side


def replay(case, traces, a, b, seed):
    """Put two planners of one case and seed on a shared clock from 0 s to the later last saved sample."""
    if a not in case['planners'] or b not in case['planners']:
        raise BadQuery('a and b must be planners of this case')
    if a == b:
        raise BadQuery('a and b must be different planners')
    if seed not in case['seeds']:
        raise BadQuery(f'unknown seed: {seed}')
    episodes = {(row['planner'], row['simulation_seed']): row for row in case['episodes']}
    sides = [_replay_side(episodes, traces, planner, seed) for planner in (a, b)]
    ends = [side['end_s'] for side in sides if side['end_s'] is not None]
    return {'seed': seed, 'duration_s': max(ends, default=0.0), 'a': sides[0], 'b': sides[1],
            'counts': {'slots': 2, 'episodes': sum(side['episode_id'] is not None for side in sides),
                       'playable': len(ends)}}
