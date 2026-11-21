"""Turn saved workflow and suite results into explorer data without planning or simulating."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from math import isfinite
from pathlib import Path
import re
from threading import Lock

import numpy as np

from raceplan.gui import analysis, run_compare, suite_view
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
# Coverage export: suite coverage.csv column names, values as in raceplan-report's "Case coverage" table; unknown counts stay blank.
COVERAGE_FIELDS = ('case_id', 'status', 'expected_episode_count', 'raw_episode_count', 'included_episode_count',
                   'missing_episode_count', 'failed_phase', 'error_type', 'error_message')
# Same conditions as the explorer table filter (전체 / 실패만 / 도달만).
EXPORT_FILTERS = {'all': lambda outcome: True, 'fail': lambda outcome: outcome != 'reached', 'ok': lambda outcome: outcome == 'reached'}


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


FORMULA_LEAD = re.compile(r'^[\s\x00-\x1f\x7f\ufeff]+')
NUMBER_LITERAL = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')


def _formula_risk(rows):
    """Spreadsheets may run cells starting with = + - @, also after blanks, control characters or a BOM.
    Only plain decimal/exponent literals are exempt; names like +INF are not."""
    for row in rows:
        for cell in row:
            text = FORMULA_LEAD.sub('', cell)
            if text[:1] in ('=', '+', '-', '@') and not NUMBER_LITERAL.fullmatch(text):
                return True
    return False


def _download_name(ids, suffix):
    """Ids without path separators, Windows-reserved or control characters; the suffix always survives shortening."""
    return re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', '-', '-'.join(ids))[:120] + f'-{suffix}.csv'


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def _strict_csv(path):
    """Saved CSV rows as dicts, refusing what DictReader would hide: repeated column names, rows of another width and
    malformed quoting (strict parsing)."""
    try:
        rows = list(csv.reader(StringIO(Reader().data(path).decode('utf-8-sig'), newline=''), strict=True))
    except csv.Error as exc:
        raise ValueError(f'{path.name} is not well-formed CSV: {exc}') from None
    if not rows:
        raise ValueError(f'{path.name} is empty')
    header = rows[0]
    if len(set(header)) != len(header):
        raise ValueError(f'{path.name} repeats a column name')
    for number, row in enumerate(rows[1:], 2):
        if len(row) != len(header):
            raise ValueError(f'{path.name} line {number} has {len(row)} cells for {len(header)} columns')
    return [dict(zip(header, row)) for row in rows[1:]]


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


WATCH_NOTE = re.compile(r'[0-9a-f]{1,32}')


def _utc(text):
    """A saved finish time as an aware UTC datetime, or None when it is missing or not a full ISO time with a zone."""
    try:
        moment = datetime.fromisoformat(text) if isinstance(text, str) else None
    except ValueError:
        return None
    return moment.astimezone(timezone.utc) if moment is not None and moment.tzinfo is not None else None


def _watch_record(folder, state_path):
    """The explorer's own note of which watch run made this folder (gui-runs/.run-meta/<run>.json, outside the engine
    output). Trusted only inside a gui-runs folder, in the expected form, about this folder, and only while the run's
    state file is still the one the note was written for; otherwise None ("no watch record")."""
    if folder.parent.name != 'gui-runs':
        return None
    path = folder.parent / '.run-meta' / f'{folder.name}.json'
    if path.resolve().parent != folder.parent.resolve() / '.run-meta':
        return None  # A link out of gui-runs/.run-meta is not this explorer's note.
    try:
        note = _read_json(path)
        state_hash = sha256(state_path.read_bytes()).hexdigest()
    except (OSError, ValueError):
        return None
    if (not isinstance(note, dict) or note.get('schema_version') != 1 or note.get('run') != folder.name
            or note.get('state_sha256') != state_hash or type(note.get('watch_run')) is not int or note['watch_run'] < 1
            or not isinstance(note.get('watch_session'), str) or not WATCH_NOTE.fullmatch(note['watch_session'])
            or note.get('trigger') not in ('start', 'change')):
        return None
    return {key: note[key] for key in ('watch_session', 'watch_run', 'trigger')}


def _case_manifest(folder, case_id):
    """A completed suite case's manifest, refusing ids and links that lead outside the run folder."""
    if not isinstance(case_id, str) or Path(case_id).name != case_id or case_id in {'', '.', '..'}:
        raise ValueError(f'invalid saved case id: {case_id!r}')
    path = (folder / 'cases' / case_id / 'comparison_manifest.json').resolve()
    if folder.resolve() not in path.parents:
        raise ValueError(f'case {case_id} leads outside its run folder')
    return _read_json(path)


def _saved_manifests(folder, state, is_suite):
    """(completed case manifests, number of cases the run was asked to do), read from saved files only."""
    if is_suite:
        cases = state.get('cases') if isinstance(state.get('cases'), dict) else {}
        done = [case_id for case_id, record in cases.items() if isinstance(record, dict) and record.get('status') == 'complete']
        return [(case_id, _case_manifest(folder, case_id)) for case_id in done], len(cases)
    manifest = (folder / 'comparison_manifest.json').resolve()
    if state.get('status') != 'complete' or not manifest.is_file() or manifest.parent != folder.resolve():
        return [], 1
    return [(folder.name, _read_json(manifest))], 1


def _run_summary(root, folder, meta_cache=None):
    state_path = _state_file(folder)
    is_suite = state_path.name == 'suite.json'
    info = state_path.stat()
    summary = {'id': folder.relative_to(root).as_posix(), 'name': folder.name, 'kind': 'suite' if is_suite else 'batch',
               'modified': info.st_mtime, 'status': 'unreadable', 'outcomes': {}, 'episodes': 0, 'meta': None}
    try:
        if state_path.resolve().parent != folder.resolve():
            raise ValueError('the state file leads outside its run folder')
        state = _read_json(state_path)
        summary['status'] = state.get('status', 'unknown')
        episodes = folder / ('episodes.csv' if is_suite else 'analysis/episodes.csv')
        if episodes.is_file():
            with episodes.open(newline='', encoding='utf-8-sig') as stream:
                outcomes = Counter(row.get('failure_class', '') for row in csv.DictReader(stream))
            summary['outcomes'] = dict(outcomes)
            summary['episodes'] = sum(outcomes.values())
    except (OSError, ValueError, AttributeError, csv.Error):
        summary['status'] = 'unreadable'
        return summary
    try:  # Versions and conditions for the list; a run whose files cannot say this still lists, without them.
        note = folder.parent / '.run-meta' / f'{folder.name}.json'
        key = (info.st_mtime_ns, info.st_size, note.stat().st_mtime_ns if note.is_file() else None)
        cached = meta_cache.get(str(folder)) if meta_cache is not None else None
        if cached is not None and cached[0] == key:
            summary['meta'] = cached[1]  # A saved run's manifests do not change; only a new state or note re-reads.
        else:
            manifests, total = _saved_manifests(folder, state, is_suite)
            summary['meta'] = run_compare.run_meta(manifests, total, state.get('finished_at_utc'), _watch_record(folder, state_path))
            if meta_cache is not None:
                meta_cache[str(folder)] = (key, summary['meta'])
    except (OSError, ValueError, AttributeError, TypeError):
        pass
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
        trace['valid'] = analysis.trace_valid(trace)
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
        self._meta_cache = {}  # run folder -> (state/note signature, list meta)

    def runs(self):
        summaries = [_run_summary(self.root, folder, self._meta_cache) for folder in find_runs(self.root)]
        return sorted(summaries, key=lambda item: (-item['modified'], item['id']))

    def runs_signature(self):
        """Cheap change marker for the run list (run ids and state-file times), so the page can refresh only on change."""
        digest = sha256()
        for folder in find_runs(self.root):
            try:
                stamp = _state_file(folder).stat().st_mtime_ns
            except (OSError, AttributeError):
                stamp = 0
            digest.update(f'{folder.relative_to(self.root).as_posix()}|{stamp}\n'.encode())
            try:  # A watch note written after the run finished must also refresh the list.
                digest.update(f'{(folder.parent / ".run-meta" / f"{folder.name}.json").stat().st_mtime_ns}\n'.encode())
            except OSError:
                pass
        return digest.hexdigest()[:16]

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
            state_path = _state_file(folder)
            key = str(state_path.resolve())
            for _ in range(3):
                reader = Reader()
                cases, coverage = _load(reader, folder)
                probe = Reader()
                state = probe.json(state_path)  # Kept for status and phase; must be the bytes _load itself validated.
                if reader.hashes.get(key) in (None, probe.hashes[key]):
                    break
            else:
                raise ValueError('the run kept changing while it was read; try again in a moment')
            entry = {'signature': signature, 'folder': folder, 'reader': reader, 'coverage': coverage, 'state': state,
                     'cases': {case['id']: case for case in cases}, 'details': {}}
            # Pin each case's validated episodes.csv to its own path and hash; a redirected (symlinked) path is never exported.
            entry['episode_files'] = {}
            for case_id in entry['cases']:
                path = self._case_folder(entry, case_id) / 'analysis/episodes.csv'
                entry['episode_files'][case_id] = (path, reader.hashes.get(str(path.resolve())) if path.resolve() == path else None)
            self._cache.pop(run_id, None)
            self._cache[run_id] = entry
            while len(self._cache) > CACHE_SIZE:
                self._cache.pop(next(iter(self._cache)))
            return entry

    def _case_folder(self, entry, case_id):
        return entry['folder'] / 'cases' / case_id if (entry['folder'] / 'suite.json').is_file() else entry['folder']

    def run(self, run_id):
        return self._run_from(self._loaded(run_id), run_id)

    def _run_from(self, entry, run_id):
        """The run as one loaded snapshot describes it; callers that need more than this pass the same entry on."""
        cases = []
        for case in entry['cases'].values():
            manifest = case['manifest']
            map_path = Path(manifest['scenario']['map_path'])
            cases.append({'id': case['id'], 'scenario': manifest['scenario'].get('name', ''),
                          'map': map_path.stem, 'map_label': f'{map_path.parent.name}/{map_path.stem}',
                          'planners': list(manifest['planners']), 'seeds': list(manifest['simulation_seeds']),
                          'baseline': case.get('baseline'),
                          'episodes': [_episode(row) for row in case['episodes']],
                          'pairs': [_pair(row) for row in case['pairs']],
                          'reproduce': _reproduce(self._case_folder(entry, case['id']))})
        return {'id': run_id, 'name': entry['folder'].name, 'kind': 'suite' if self._is_suite(entry) else 'batch',
                'cases': cases, 'coverage': [
            {'case_id': row['case_id'], 'status': row['status'], 'expected': _count(row.get('expected_episode_count')),
             'included': _count(row.get('included_episode_count', 0)) or 0, 'failed_phase': row.get('failed_phase'),
             'error': (row.get('error') or {}).get('message', '')} for row in entry['coverage']]}

    @staticmethod
    def _is_suite(entry):
        return (entry['folder'] / 'suite.json').is_file()

    def _suite_cases(self, run_id):
        """One loaded snapshot of a suite and the run built from it, so totals, rows, coverage and export pins agree."""
        if not (self._folder(run_id) / 'suite.json').is_file():
            raise analysis.BadQuery('all cases together is for suite runs; open the case of this run instead')
        entry = self._loaded(run_id)
        return entry, self._run_from(entry, run_id)

    def overview(self, run_id):
        """Totals over every validated case of a suite, the planner x case matrix, all episodes with their case, and
        a check of the totals against the suite's own summary.csv / case_summary.csv. Coverage lists every case.
        The saved totals are checked once the suite has finished writing them (phase complete: complete, partial,
        interrupted and failed alike); while it runs they are not final and are not compared."""
        entry, run = self._suite_cases(run_id)
        included = [{'id': case['id'], 'planners': list(case['manifest']['planners']), 'rows': case['episodes']}
                    for case in entry['cases'].values()]
        leaderboard, matrix = suite_view.totals(included)
        status = entry['state'].get('status')
        if entry['state'].get('phase') != 'complete':
            if entry['state'].get('finished_at_utc'):  # Ended before writing its totals (failed while aggregating).
                error = entry['state'].get('error') or {}
                check = {'status': 'missing', 'message': f'the suite ended ({status}) without writing its totals'
                                                         + (f': {error.get("message")}' if error.get('message') else '')}
            else:
                check = {'status': 'not_final', 'suite_status': status}
        else:
            try:
                saved = [_strict_csv(entry['folder'] / name) for name in ('summary.csv', 'case_summary.csv')]
            except (OSError, ValueError, csv.Error) as exc:
                check = {'status': 'missing', 'message': str(exc)}
            else:
                differences = suite_view.check_saved(leaderboard, matrix, *saved)
                check = {'status': 'mismatch' if differences else 'match', 'count': len(differences),
                         'differences': differences[:50]}
        try:
            provenance = Reader().json(entry['folder'] / 'provenance.json')
        except (OSError, ValueError):
            provenance = None
        versions = (suite_view.planner_versions(provenance, [(case['id'], case['manifest']) for case in entry['cases'].values()])
                    if provenance is not None else None)
        return {'id': run_id, 'name': run['name'], 'kind': 'suite', 'status': status,
                'planners': suite_view.planner_order(included),
                'seeds': sorted({seed for case in run['cases'] for seed in case['seeds']}),
                'cases': [{key: case[key] for key in ('id', 'scenario', 'map_label', 'planners', 'seeds', 'baseline')}
                          for case in run['cases']],
                'coverage': run['coverage'], 'leaderboard': leaderboard, 'matrix': matrix,
                'episodes': [{**episode, 'case': case['id']} for case in run['cases'] for episode in case['episodes']],
                'summary_check': check, 'planner_versions': versions,
                'run': run}  # The page takes its case list and coverage from this same snapshot.

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

    def compare_all(self, run_id, kind, **options):
        """The same comparison over every validated case of a suite, pooled after the single-case rules. The included
        case ids and the listed case count come from the same snapshot as the points, so the page can tell when its
        own case list is older and read the overview again."""
        _, run = self._suite_cases(run_id)
        pooled = (suite_view.pooled_delta if kind == 'delta' else suite_view.pooled_scatter)(run['cases'], **options)
        return {**pooled, 'case_ids': [case['id'] for case in run['cases']], 'cases_listed': len(run['coverage'])}

    def _comparable(self, run_id):
        """One loaded snapshot of a run for comparing with another: its completed cases (manifest and saved episode
        rows) and what the run list says about it, all from that snapshot."""
        entry = self._loaded(run_id)
        cases = [{'id': case['id'], 'manifest': case['manifest'], 'episodes': case['episodes']} for case in entry['cases'].values()]
        coverage = entry['coverage']
        meta = run_compare.run_meta([(case['id'], case['manifest']) for case in cases], len(coverage) or 1,
                                    entry['state'].get('finished_at_utc'), _watch_record(entry['folder'], _state_file(entry['folder'])))
        status = entry['state'].get('status')
        return {'id': run_id, 'name': entry['folder'].name, 'kind': 'suite' if self._is_suite(entry) else 'batch',
                'status': status, 'complete': status == 'complete', 'meta': meta, 'cases': cases,
                'coverage': [{'case_id': row['case_id'], 'status': row['status']} for row in coverage]}

    @staticmethod
    def _auto_ready(run):
        """Can this run take part in choosing "the previous run" automatically? Complete, every case with full
        evidence (fingerprint), one version per planner, and a readable finish time."""
        meta = run['meta']
        return (run['status'] == 'complete' and meta and meta['fingerprint'] and not meta['mixed_versions']
                and _utc(meta['finished_at']) is not None)

    def _previous(self, run_id, b):
        """The latest run finished before B with the same cases (saved input hashes), conditions, seeds, planner names,
        engine and runtime; None when there is none or B itself cannot say. Planner code may differ: that is the
        comparison."""
        if not self._auto_ready(b):
            return None
        mine = _utc(b['meta']['finished_at'])
        found = [run for run in self.runs() if run['id'] != run_id and self._auto_ready(run)
                 and run['meta']['fingerprint'] == b['meta']['fingerprint'] and _utc(run['meta']['finished_at']) < mine]
        return max(found, key=lambda run: (_utc(run['meta']['finished_at']), run['id']))['id'] if found else None

    def compare_runs(self, b_id, a_id=None):
        """Run B against run A (by default the previous run of the same conditions): one loaded snapshot of each, the
        header facts and every number of the answer come from those two snapshots."""
        if a_id is not None and a_id == b_id:
            raise analysis.BadQuery('choose two different runs')
        b = self._comparable(b_id)
        suggested, note = a_id is None, None
        if suggested:
            a_id = self._previous(b_id, b)
        a = self._comparable(a_id) if a_id else None
        if suggested and a is not None and not (self._auto_ready(a) and a['meta']['fingerprint'] == b['meta']['fingerprint']
                                                 and _utc(a['meta']['finished_at']) < _utc(b['meta']['finished_at'])):
            # The list said "same conditions" but the loaded run does not: never present it as the previous run.
            a, note = None, 'changed_on_load'  # the run found as the previous one no longer matches once loaded
        if suggested and a is None and note is None:
            # not_ready: B is not complete, mixes planner versions, has cases without full records or no finish time;
            # none: no earlier complete run with the same cases, conditions, seeds, planners, engine and runtime.
            note = 'not_ready' if not self._auto_ready(b) else 'none'
        result = run_compare.compare(a, b) if a else None
        if result is not None:
            for run in (a, b):
                if run['status'] != 'complete':
                    result['issues'].insert(0, f'{run["name"]} is {run["status"]}: only its completed cases are compared')
        strip = ('cases',)
        return {'a': {key: value for key, value in a.items() if key not in strip} if a else None,
                'b': {key: value for key, value in b.items() if key not in strip}, 'suggested': suggested,
                'note': note, 'result': result}

    def replay(self, run_id, case_id, a, b, seed):
        detail = self.case(run_id, case_id)
        case = next(item for item in self.run(run_id)['cases'] if item['id'] == case_id)
        return analysis.replay(case, detail['traces'], a, b, seed)

    def _saved_episode_rows(self, entry, case_id):
        """The validated analysis/episodes.csv of one case as stored (header and cell text), or ValueError."""
        path, digest = entry['episode_files'][case_id]
        if digest is None or path.resolve() != path:
            raise ValueError('saved episodes.csv is redirected outside its case folder; reopen the run')
        data = path.read_bytes()
        # Export exactly the bytes this case validated; a later edit must not slip through the cache.
        if sha256(data).hexdigest() != digest:
            raise ValueError('saved episodes.csv changed after it was validated; reopen the run')
        rows = [row for row in csv.reader(StringIO(data.decode('utf-8-sig'), newline='')) if row]  # Blank records, as DictReader.
        if not rows or len(set(rows[0])) != len(rows[0]):
            raise ValueError('saved episodes.csv needs one header with unique column names')
        return rows

    def export_episodes(self, run_id, case_id, filter='all'):
        """Rows of the saved analysis/episodes.csv as stored (header, cell text, order), limited to the table filter."""
        if filter not in EXPORT_FILTERS:
            raise analysis.BadQuery(f'unknown filter: {filter}')
        entry = self._loaded(run_id)
        if case_id not in entry['cases']:
            raise UnknownItem(f'unknown or incomplete case: {case_id}')
        rows = self._saved_episode_rows(entry, case_id)
        column, keep = rows[0].index('failure_class'), EXPORT_FILTERS[filter]
        selected = [row for row in rows[1:] if keep(row[column] if column < len(row) else '')]
        return [rows[0], *selected], _download_name((run_id, case_id), f'episodes-{filter}')

    def export_suite_episodes(self, run_id, filter='all'):
        """Every validated case's saved episodes.csv in case order and file order, each row led by its case_id,
        limited to the table filter. All or nothing: one changed or mismatched file fails the whole export."""
        if filter not in EXPORT_FILTERS:
            raise analysis.BadQuery(f'unknown filter: {filter}')
        entry, run = self._suite_cases(run_id)
        header, out = None, []
        for case in run['cases']:
            rows = self._saved_episode_rows(entry, case['id'])
            if header is None:
                header = rows[0]
                if 'case_id' in header:
                    raise ValueError(f'saved episodes.csv of case {case["id"]} already has a case_id column')
            elif rows[0] != header:
                raise ValueError(f'saved episodes.csv of case {case["id"]} has different columns from the other cases')
            if any(len(row) != len(header) for row in rows[1:]):
                raise ValueError(f'saved episodes.csv of case {case["id"]} has a row whose cell count differs from its header')
            column, keep = rows[0].index('failure_class'), EXPORT_FILTERS[filter]
            out += [[case['id'], *row] for row in rows[1:] if keep(row[column])]
        if header is None:
            raise UnknownItem('this suite has no completed case to export')
        return [['case_id', *header], *out], _download_name((run_id,), f'all-cases-episodes-{filter}')

    def export_coverage(self, run_id):
        """Every case of the run, including failed or unfinished ones, with the counts the page and report show.
        Coverage is re-read and re-validated on each export, like raceplan-report, instead of trusting the page cache."""
        _, coverage = _load(Reader(), self._folder(run_id))
        rows = [list(COVERAGE_FIELDS)]
        for record in coverage:
            expected, included = _count(record.get('expected_episode_count')), _count(record.get('included_episode_count', 0)) or 0
            error = record.get('error') if isinstance(record.get('error'), dict) else {}
            values = (record.get('case_id'), record.get('status'), expected, _count(record.get('raw_episode_count')), included,
                      None if expected is None else expected - included, record.get('failed_phase'), error.get('type'), error.get('message'))
            rows.append(['' if value is None else str(value) for value in values])
        return rows, _download_name((run_id,), 'coverage')
