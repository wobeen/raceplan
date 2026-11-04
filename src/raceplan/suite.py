"""Run strict YAML cases through workflow and aggregate completed-case results."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import fields
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from shutil import copyfile
import sys
from time import perf_counter
import csv

import numpy as np
import yaml

from raceplan import experiment, workflow
from raceplan.common import load_occupancy_map, load_scenario
from raceplan.planners.execution import _diagnostic, ERROR_MESSAGE_LIMIT, ERROR_TYPE_LIMIT
from raceplan.simulator import NoiseConfig


class StrictLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError(f'configuration keys must be unique strings: {key!r}')
        result[key] = loader.construct_object(value_node)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def _mapping(value, allowed, required=()):
    if not isinstance(value, dict) or not set(value) <= set(allowed) or not set(required) <= set(value):
        raise ValueError(f'expected mapping with keys {sorted(allowed)}; required {sorted(required)}')
    return value


def _strings(value, label, *, nonempty=True):
    if (not isinstance(value, list) or (nonempty and not value)
            or any(not isinstance(item, str) or not item.strip() or item != item.strip() for item in value)):
        raise ValueError(f'{label} must be a list of non-empty trimmed strings')
    if len(set(value)) != len(value):
        raise ValueError(f'{label} must be unique')
    return value


def _number(value, label, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be a finite number')
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError(f'{label} must be finite') from exc
    if not isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "non-negative"}')
    return number


def _seed(value, label):
    if type(value) is not int or value < 0:
        raise ValueError(f'{label} must be a non-negative integer')
    return value


def _hash(path):
    return sha256(path.read_bytes()).hexdigest()


def load_config(path):
    """Validate all static inputs without importing custom Python code."""
    path = path.resolve()
    data = yaml.load(path.read_text(encoding='utf-8'), Loader=StrictLoader)
    allowed = {'version', 'cases', 'planners', 'custom_planners', 'simulation_seeds', 'noise',
               'inflation_radius_m', 'baseline', 'report_seed', 'spacing_m'}
    _mapping(data, allowed, {'version', 'cases'})
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('version must be integer 1')
    planners = _strings(data.get('planners', list(experiment.PLANNER_FACTORIES)), 'planners')
    if not set(planners) <= set(experiment.PLANNER_FACTORIES):
        raise ValueError('unknown builtin planner')
    custom = []
    custom_inputs = {}
    for spec in _strings(data.get('custom_planners', []), 'custom_planners', nonempty=False):
        filename, separator, classname = spec.rpartition(':')
        source = (path.parent / filename).resolve()
        if not separator or not filename or not classname.isidentifier() or not source.is_file() or source.suffix.lower() != '.py':
            raise ValueError(f'invalid custom planner file/class: {spec}')
        custom.append(f'{source}:{classname}')
        custom_inputs[str(source)] = _hash(source)
    if len(set(custom)) != len(custom):
        raise ValueError('resolved custom planner specifications must be unique')
    seeds = data.get('simulation_seeds')
    if 'simulation_seeds' in data:
        if not isinstance(seeds, list) or not seeds:
            raise ValueError('simulation_seeds must be a non-empty list')
        seeds = [_seed(seed, 'simulation seed') for seed in seeds]
        if len(set(seeds)) != len(seeds):
            raise ValueError('simulation seeds must be unique')
    baseline = data.get('baseline', 'astar' if 'astar' in planners else planners[0])
    if not isinstance(baseline, str) or not baseline.strip() or baseline != baseline.strip():
        raise ValueError('baseline must be a non-empty trimmed string')
    if baseline not in planners and not custom:
        raise ValueError('baseline must be a selected planner')
    report_seed = _seed(data['report_seed'], 'report_seed') if 'report_seed' in data else None
    noise_names = {field.name for field in fields(NoiseConfig)}
    noise = _mapping(data.get('noise', {}), noise_names)
    noise = {name: _number(noise.get(name, 0.0), f'noise.{name}') for name in sorted(noise_names)}
    settings = {'planners': planners, 'custom_planners': custom, 'baseline': baseline,
                'noise': noise, 'inflation_radius_m': _number(data.get('inflation_radius_m', 0.0), 'inflation_radius_m'),
                'spacing_m': _number(data.get('spacing_m', .1), 'spacing_m', positive=True)}
    if not isinstance(data['cases'], list) or not data['cases']:
        raise ValueError('cases must be a non-empty list')
    cases, used_ids = [], set()
    reserved = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{index}' for prefix in ('com', 'lpt') for index in range(1, 10)}
    for item in data['cases']:
        _mapping(item, {'id', 'scenario'}, {'id', 'scenario'})
        identity = item['id']
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', identity)
                or identity.casefold() in reserved or identity.casefold() in used_ids):
            raise ValueError('case id must be safe, unique ignoring case, and not a Windows reserved name')
        used_ids.add(identity.casefold())
        if not isinstance(item['scenario'], str) or not item['scenario'].strip():
            raise ValueError('case scenario must be a non-empty path string')
        scenario_path = (path.parent / item['scenario']).resolve()
        scenario = load_scenario(scenario_path)
        metadata = load_occupancy_map(scenario.map_path)
        selected_seeds = seeds if seeds is not None else [scenario.simulation_seed]
        if report_seed is not None and report_seed not in selected_seeds:
            raise ValueError(f'report_seed is absent from case {identity}')
        inputs = {str(source): _hash(source) for source in (path, scenario_path, metadata.yaml_path, metadata.image_path)}
        cases.append({'id': identity, 'scenario': str(scenario_path), 'scenario_name': scenario.name,
                      'simulation_seeds': selected_seeds, 'report_seed': selected_seeds[0] if report_seed is None else report_seed,
                      'expected_episode_count': (len(planners) + len(custom)) * len(selected_seeds),
                      'input_sha256': inputs | custom_inputs})
    return {'version': 1, 'config_file': str(path), 'settings': settings, 'cases': cases}


def _command(case, settings, output):
    command = [case['scenario'], '--output-dir', str(output), '--planners', *settings['planners'],
               '--simulation-seeds', *map(str, case['simulation_seeds']), '--baseline=' + settings['baseline'],
               '--report-seed', str(case['report_seed']), '--spacing', str(settings['spacing_m']),
               '--inflation-radius', str(settings['inflation_radius_m'])]
    for spec in settings['custom_planners']:
        command.append('--custom-planner=' + spec)
    for name, value in settings['noise'].items():
        command += ['--' + name.replace('_', '-'), str(value)]
    return command


def _read(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def _write(path, rows, columns):
    keys = list(dict.fromkeys(columns + [key for row in rows for key in row]))
    with path.open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _collect(case, folder):
    manifest = json.loads((folder / 'comparison_manifest.json').read_text(encoding='utf-8'))
    episodes = _read(folder / 'analysis/episodes.csv')
    expected = {(name, str(seed)) for name in manifest['planners'] for seed in case['simulation_seeds']}
    observed = [(row['planner'], row['simulation_seed']) for row in episodes]
    if (manifest['status'] != 'complete' or len(episodes) != case['expected_episode_count']
            or len(set(observed)) != len(observed) or set(observed) != expected):
        raise ValueError('completed case episode coverage does not match its configuration')
    dimensions = {'case_id': case['id'], 'scenario_file': case['scenario'], 'scenario': case['scenario_name']}
    plans, seen = [], set()
    for row in episodes:
        row.update(dimensions)
        row['episode_key'] = f'{case["id"]}:{row["planner"]}:{row["simulation_seed"]}'
        row['plan_key'] = f'{case["id"]}:{row["plan_id"]}'
        if row['plan_key'] not in seen:
            seen.add(row['plan_key'])
            plans.append(dimensions | {key: row.get(key, '') for key in (
                'plan_key', 'plan_id', 'planner', 'planning_status', 'path_cost_m', 'expanded_nodes',
                'planning_time_ms', 'runner_planning_time_ms', 'planning_error_type', 'planning_error_message',
                'planning_error_truncated', 'path_length_m', 'total_absolute_turn_rad')})
    pair_path = folder / 'analysis/paired.csv'
    pairs = _read(pair_path) if pair_path.exists() else []
    if len(pairs) != (len(manifest['planners']) - 1) * len(case['simulation_seeds']):
        raise ValueError('completed case paired coverage does not match its configuration')
    for row in pairs:
        row.update(dimensions)
        row['pair_key'] = f'{case["id"]}:{row["planner"]}:{row["simulation_seed"]}'
    return episodes, plans, pairs


def _summaries(episodes, plans, by_case):
    groups, timings = defaultdict(list), defaultdict(list)
    key = lambda row: (row['case_id'], row['planner']) if by_case else (row['planner'],)
    for row in episodes:
        groups[key(row)].append(row)
    for row in plans:
        timings[key(row)].append(row)
    summaries = []
    for group, rows in groups.items():
        reached = [row for row in rows if row['failure_class'] == 'reached']
        summary = {'case_id': group[0] if by_case else 'ALL', 'planner': group[-1],
                   'episodes_recorded': len(rows), 'reached': len(reached),
                   'reach_rate_observed': len(reached) / len(rows),
                   'collisions': sum(row['collision'] == 'True' for row in rows),
                   'timeouts': sum(row['simulation_status'] == 'timeout' for row in rows),
                   'planning_failures': sum(row['planning_status'] != 'success' for row in rows),
                   'planning_errors': sum(row['planning_status'] == 'planning_error' for row in rows),
                   'planning_calls': len(timings[group])}
        for metric in ('tracking_rmse_m', 'completion_time_s', 'steering_saturation_fraction'):
            summary['success_median_' + metric] = float(np.median([float(row[metric]) for row in reached])) if reached else None
        for metric in ('planning_time_ms', 'runner_planning_time_ms'):
            values = [float(row[metric]) for row in timings[group] if row[metric] != '']
            summary[metric + '_samples'] = len(values)
            summary[metric + '_median'] = float(np.median(values)) if values else None
            summary[metric + '_p95'] = float(np.quantile(values, .95)) if values else None
        summaries.append(summary)
    return summaries


def _coverage(state):
    records = list(state['cases'].values())
    return {'expected_cases': len(records), 'completed_cases': sum(r['status'] == 'complete' for r in records),
            'failed_cases': sum(r['status'] == 'failed' for r in records),
            'not_run_cases': sum(r['status'] in {'pending', 'not_run'} for r in records),
            'expected_episode_count': sum(r['expected_episode_count'] for r in records),
            'included_episode_count': sum(r['included_episode_count'] for r in records),
            'missing_episode_count': sum(r['expected_episode_count'] - r['included_episode_count'] for r in records)}


def _error(exc):
    try:
        text = str(exc)
    except Exception:
        text = '<exception message unavailable>'
    name, name_truncated = _diagnostic(type(exc).__name__, ERROR_TYPE_LIMIT)
    message, truncated = _diagnostic(text, ERROR_MESSAGE_LIMIT)
    return {'type': name, 'message': message, 'truncated': truncated or name_truncated}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('config', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() or args.output_dir.is_symlink():
        parser.error('output directory already exists; choose a new --output-dir')
    try:
        config = load_config(args.config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    output.mkdir(parents=True, exist_ok=False)
    resolved_path = output / 'resolved_config.json'
    workflow._save_state(resolved_path, config)
    copyfile(args.config.resolve(), output / 'config_snapshot.yaml')
    provenance = {'resolved_config_sha256': _hash(resolved_path),
                  'input_sha256': {path: value for case in config['cases'] for path, value in case['input_sha256'].items()},
                  'source_sha256': {str(path): _hash(path) for path in sorted(Path(__file__).parent.rglob('*.py'))}}
    workflow._save_state(output / 'provenance.json', provenance)
    state = {'schema_version': 1, 'status': 'running', 'phase': 'cases', 'created_at_utc': workflow._timestamp(),
             'cases': {case['id']: {'case_id': case['id'], 'status': 'pending',
                                  'expected_episode_count': case['expected_episode_count'],
                                  'raw_episode_count': 0, 'included_episode_count': 0}
                       for case in config['cases']}}
    state_path = output / 'suite.json'
    workflow._save_state(state_path, state)
    episodes, plans, pairs, stop_code = [], [], [], None
    for case in config['cases']:
        record = state['cases'][case['id']]
        record.update(status='running', started_at_utc=workflow._timestamp())
        workflow._save_state(state_path, state)
        folder = output / 'cases' / case['id']
        started = perf_counter()
        try:
            for filename, expected in case['input_sha256'].items():
                if _hash(Path(filename)) != expected:
                    raise ValueError(f'input changed since suite preflight: {filename}')
            code = workflow.main(_command(case, config['settings'], folder))
            run_state = json.loads((folder / 'workflow.json').read_text(encoding='utf-8'))
            if code != 0 or run_state['status'] != 'complete':
                record.update(status='failed', failed_phase=run_state.get('failed_phase'), error=run_state.get('error', {}))
                if record['error'].get('control_exception', False):
                    stop_code = code or 1
            else:
                local_episodes, local_plans, local_pairs = _collect(case, folder)
                episodes.extend(local_episodes)
                plans.extend(local_plans)
                pairs.extend(local_pairs)
                record.update(status='complete', included_episode_count=len(local_episodes))
        except (KeyboardInterrupt, SystemExit) as exc:
            record.update(status='failed', failed_phase='invocation', error=_error(exc))
            stop_code = 130 if isinstance(exc, KeyboardInterrupt) else (exc.code if isinstance(exc.code, int) and exc.code else 1)
        except Exception as exc:
            record.update(status='failed', failed_phase='execution_or_collection', error=_error(exc))
        try:
            record['raw_episode_count'] = len(_read(folder / 'comparison.csv')) if (folder / 'comparison.csv').exists() else 0
        except (OSError, UnicodeError, csv.Error):
            record['raw_episode_count'] = None
        record.update(finished_at_utc=workflow._timestamp(), duration_s=perf_counter() - started)
        state['coverage'] = _coverage(state)
        workflow._save_state(state_path, state)
        if stop_code is not None:
            break
    for record in state['cases'].values():
        if record['status'] == 'pending':
            record['status'] = 'not_run'
    state.update(phase='aggregation', coverage=_coverage(state))
    workflow._save_state(state_path, state)
    try:
        _write(output / 'episodes.csv', episodes, ['case_id', 'scenario', 'scenario_file', 'planner', 'simulation_seed', 'episode_key', 'plan_key'])
        _write(output / 'planning.csv', plans, ['case_id', 'scenario', 'scenario_file', 'planner', 'plan_key'])
        _write(output / 'paired.csv', pairs, ['case_id', 'scenario', 'scenario_file', 'planner', 'baseline', 'simulation_seed', 'pair_key'])
        coverage_complete = state['coverage']['missing_episode_count'] == 0
        summary = [row | {'coverage_complete': coverage_complete, **state['coverage']}
                   for row in _summaries(episodes, plans, False)]
        _write(output / 'summary.csv', summary, ['planner', 'episodes_recorded', 'coverage_complete'])
        _write(output / 'case_summary.csv', _summaries(episodes, plans, True), ['case_id', 'planner', 'episodes_recorded'])
        coverage_rows = [{key: value for key, value in record.items() if key != 'error'} | {
            'missing_episode_count': record['expected_episode_count'] - record['included_episode_count'],
            'error_type': record.get('error', {}).get('type', ''),
            'error_message': _diagnostic(record.get('error', {}).get('message', ''), ERROR_MESSAGE_LIMIT)[0],
        } for record in state['cases'].values()]
        _write(output / 'coverage.csv', coverage_rows, ['case_id', 'status', 'expected_episode_count', 'raw_episode_count', 'included_episode_count'])
    except Exception as exc:
        state.update(status='failed', error=_error(exc), finished_at_utc=workflow._timestamp())
        workflow._save_state(state_path, state)
        return 1
    failed = state['coverage']['failed_cases'] > 0
    result_status = ('interrupted' if stop_code is not None else
                     'partial' if failed and state['coverage']['completed_cases'] else 'failed' if failed else 'complete')
    state.update(status=result_status,
                 phase='complete', finished_at_utc=workflow._timestamp(),
                 aggregation_note='completed workflow cases only; missing coverage is not synthesized as episodes')
    workflow._save_state(state_path, state)
    print(f'suite={state_path}\ncoverage={state["coverage"]}')
    return stop_code if stop_code is not None else 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
