"""Turn saved workflow and suite results into explorer data without planning or simulating."""
from __future__ import annotations

from collections import Counter
import csv
import json
from math import isfinite
from pathlib import Path
from threading import Lock

import numpy as np

from raceplan.gui import analysis
from raceplan.report import Reader, _load

STATE_FILES = ('suite.json', 'workflow.json', 'comparison_manifest.json')
SCAN_DEPTH = 3
CACHE_SIZE = 4
EPISODE_NUMBERS = ('tracking_rmse_m', 'completion_time_s', 'goal_distance_m', 'max_tracking_error_m',
                   'planning_time_ms', 'runner_planning_time_ms', 'path_length_m',
                   'driving_min_sampled_clearance_m', 'driving_min_clearance_time_s')
EPISODE_TEXTS = ('episode_id', 'plan_id', 'planner', 'failure_class', 'planning_status', 'simulation_status',
                 'planning_error_type', 'planning_error_message')
PAIR_NUMBERS = ('delta_tracking_rmse_m', 'delta_completion_time_s', 'delta_driving_min_sampled_clearance_m')
TRACE_FIELDS = {'t': 'time_s', 'x': 'x_m', 'y': 'y_m', 'speed': 'speed_mps',
                'steering': 'steering_angle_rad', 'error': 'tracking_error_m'}


class UnknownItem(LookupError):
    """The requested run or case is not part of the explorer root."""


def _number(value, digits=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(number):
        return None
    return round(number, digits) if digits is not None else number


def _count(value):
    """Coverage counts are shown in the page, so anything that is not a plain integer becomes unknown."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _state_file(folder):
    for name in STATE_FILES:
        if (folder / name).is_file():
            return folder / name
    return None


def find_runs(root):
    """Return saved run folders under root; a run's own subfolders are never treated as runs."""
    found = []

    def visit(folder, level):
        if _state_file(folder):
            found.append(folder)
            return
        if level == SCAN_DEPTH:
            return
        try:
            children = sorted(child for child in folder.iterdir() if child.is_dir() and not child.is_symlink())
        except OSError:
            return
        for child in children:
            visit(child, level + 1)

    visit(Path(root), 0)
    return found


def _run_summary(root, folder):
    state_path = _state_file(folder)
    is_suite = state_path.name == 'suite.json'
    summary = {'id': folder.relative_to(root).as_posix(), 'name': folder.name, 'kind': 'suite' if is_suite else 'batch',
               'modified': state_path.stat().st_mtime, 'status': 'unreadable', 'outcomes': {}, 'episodes': 0}
    try:
        summary['status'] = _read_json(state_path).get('status', 'unknown')
        episodes = folder / ('episodes.csv' if is_suite else 'analysis/episodes.csv')
        if episodes.is_file():
            with episodes.open(newline='', encoding='utf-8-sig') as stream:
                outcomes = Counter(row.get('failure_class', '') for row in csv.DictReader(stream))
            summary['outcomes'] = dict(outcomes)
            summary['episodes'] = sum(outcomes.values())
    except (OSError, ValueError, AttributeError, csv.Error):
        summary['status'] = 'unreadable'
    return summary


def _episode(row):
    episode = {key: row.get(key, '') for key in EPISODE_TEXTS}
    episode['simulation_seed'] = int(row['simulation_seed'])
    episode.update({key: _number(row.get(key)) for key in EPISODE_NUMBERS})
    return episode


def _pair(row):
    pair = {'planner': row['planner'], 'baseline': row['baseline'], 'simulation_seed': int(row['simulation_seed']),
            'both_reached': row['both_reached'] == 'True', 'both_driven': row['both_driven'] == 'True'}
    pair.update({key: _number(row.get(key)) for key in PAIR_NUMBERS})
    return pair


def _reproduce(folder):
    """Rebuild the saved experiment command, pointing it at a new output file."""
    path = folder / 'workflow.json'
    if not path.is_file():
        return None
    arguments = list(_read_json(path)['phases']['experiment']['arguments'])
    arguments[arguments.index('--output') + 1] = 'NEW_FOLDER/comparison.csv'
    return ['raceplan-run', *arguments]


def _occupied_runs(grid):
    """Encode occupied cells as [row, first column, length] so large maps stay small."""
    runs = []
    for row, cells in enumerate(np.asarray(grid.occupied, dtype=np.int8)):
        edges = np.flatnonzero(np.diff(np.concatenate(([0], cells, [0]))))
        runs.extend([row, int(first), int(last - first)] for first, last in zip(edges[::2], edges[1::2]))
    return runs


def _clearances(reader, folder):
    path = folder / 'analysis/clearance_samples.csv'
    series = {}
    if path.is_file():
        for row in reader.csv(path):
            series.setdefault(row['episode_id'], {})[int(row['step'])] = _number(row['footprint_clearance_m'], 5)
    return series


def _case_detail(reader, case, folder):
    grid, manifest = case['grid'], case['manifest']
    clearances = _clearances(reader, folder)
    traces = {}
    for episode_id, samples in case['traces'].items():
        trace = {name: [_number(sample[field], 5) for sample in samples] for name, field in TRACE_FIELDS.items()}
        saved = clearances.get(episode_id, {})
        trace['clearance'] = [saved.get(step) for step in range(len(samples))] if saved else None
        traces[episode_id] = trace
    scenario = manifest['scenario']
    return {'id': case['id'], 'start': scenario['start'], 'goal': scenario['goal'],
            'goal_tolerance': _number(manifest.get('simulation', {}).get('goal_tolerance')),
            'grid': {'width': grid.width, 'height': grid.height, 'resolution': grid.resolution,
                     'origin_x': grid.origin_x, 'origin_y': grid.origin_y, 'occupied': _occupied_runs(grid)},
            'paths': {plan_id: [[_number(p['x_m'], 5), _number(p['y_m'], 5)] for p in points]
                      for plan_id, points in case['paths'].items()},
            'traces': traces}


class Explorer:
    """Read-only access to saved runs below one root folder."""

    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = Lock()
        self._cache = {}

    def runs(self):
        summaries = [_run_summary(self.root, folder) for folder in find_runs(self.root)]
        return sorted(summaries, key=lambda item: (-item['modified'], item['id']))

    def _folder(self, run_id):
        for folder in find_runs(self.root):
            if folder.relative_to(self.root).as_posix() == run_id:
                return folder
        raise UnknownItem(f'unknown run: {run_id}')

    def _loaded(self, run_id):
        folder = self._folder(run_id)
        signature = _state_file(folder).stat().st_mtime_ns
        with self._lock:
            entry = self._cache.get(run_id)
            if entry and entry['signature'] == signature:
                return entry
            reader = Reader()
            cases, coverage = _load(reader, folder)
            entry = {'signature': signature, 'folder': folder, 'reader': reader, 'coverage': coverage,
                     'cases': {case['id']: case for case in cases}, 'details': {}}
            self._cache.pop(run_id, None)
            self._cache[run_id] = entry
            while len(self._cache) > CACHE_SIZE:
                self._cache.pop(next(iter(self._cache)))
            return entry

    def _case_folder(self, entry, case_id):
        return entry['folder'] / 'cases' / case_id if (entry['folder'] / 'suite.json').is_file() else entry['folder']

    def run(self, run_id):
        entry = self._loaded(run_id)
        cases = []
        for case in entry['cases'].values():
            manifest = case['manifest']
            cases.append({'id': case['id'], 'scenario': manifest['scenario'].get('name', ''),
                          'map': Path(manifest['scenario']['map_path']).stem,
                          'planners': list(manifest['planners']), 'seeds': list(manifest['simulation_seeds']),
                          'baseline': case.get('baseline'),
                          'episodes': [_episode(row) for row in case['episodes']],
                          'pairs': [_pair(row) for row in case['pairs']],
                          'reproduce': _reproduce(self._case_folder(entry, case['id']))})
        return {'id': run_id, 'name': entry['folder'].name, 'cases': cases, 'coverage': [
            {'case_id': row['case_id'], 'status': row['status'], 'expected': _count(row.get('expected_episode_count')),
             'included': _count(row.get('included_episode_count', 0)) or 0, 'failed_phase': row.get('failed_phase'),
             'error': (row.get('error') or {}).get('message', '')} for row in entry['coverage']]}

    def case(self, run_id, case_id):
        entry = self._loaded(run_id)
        if case_id not in entry['cases']:
            raise UnknownItem(f'unknown case: {case_id}')
        with self._lock:
            if case_id not in entry['details']:
                entry['details'][case_id] = _case_detail(entry['reader'], entry['cases'][case_id],
                                                         self._case_folder(entry, case_id))
            return entry['details'][case_id]

    def compare(self, run_id, case_id, kind, **options):
        entry = self._loaded(run_id)
        if case_id not in entry['cases']:
            raise UnknownItem(f'unknown case: {case_id}')
        case = next(item for item in self.run(run_id)['cases'] if item['id'] == case_id)
        if kind == 'delta':
            return analysis.paired_delta(case, **options)
        return analysis.scatter(case, **options)
