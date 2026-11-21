"""Run comparisons for the explorer in a separate process, never inside the server process.

A job is one ``raceplan.workflow`` call, or one ``raceplan.suite`` call when it covers several scenarios or adds
noise (both through raceplan.gui.workflow_runner, which only makes their state saves tolerate the explorer reading
them on Windows). Requests are validated against what the server lists (scenarios, built-in planners) before anything
starts; a suite's generated config is checked with raceplan.suite's own static validation, which runs no user code.
User planner files are only checked for existence here and are loaded, and therefore executed, by the comparison
process. One job runs at a time, with one time limit for the whole job and cancellation; stopping a running job kills
its process tree (taskkill /T on Windows, the process group on POSIX) and records the stop in the job's own
workflow.json or suite.json the way workflow.py records an interrupt. Processes a planner started and left running
after the comparison itself ended are not tracked and are not stopped.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import fields
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import threading
import time

import yaml

from raceplan import experiment, suite, workflow
from raceplan.common import load_scenario
from raceplan.gui import suite_view
from raceplan.gui.frozen import workflow_command, worker_folder
from raceplan.gui.workflow_runner import START_SIGNAL, SUITE
from raceplan.simulator.noise import NoiseConfig

OUTPUT_FOLDER = 'gui-runs'
SUITE_INPUTS = '.suite-inputs'  # Generated suite configs, kept next to the runs (each run also keeps its own copy).
LOG_LINES = 400
LOG_LINE_CHARS = 2000
READ_LIMIT = 64 * 1024  # One read never holds more than this, even if a planner prints without newlines.
KEEP_FINISHED = 20
MAX_CUSTOM_PLANNERS = 8
MAX_SEEDS = 50
MAX_CASES = 16
MAX_CASE_SEEDS = 200  # scenarios x seeds
MAX_EPISODES = 1000  # scenarios x seeds x planners
SEED_LIMIT = 2**31 - 1
NOISE_FIELDS = tuple(field.name for field in fields(NoiseConfig))
FIELDS = {'scenario', 'scenarios', 'planners', 'custom_planners', 'seeds', 'baseline', 'noise', 'trust_user_code'}
RESERVED_IDS = {'con', 'prn', 'aux', 'nul'} | {f'{prefix}{index}' for prefix in ('com', 'lpt') for index in range(1, 10)}
FINISH_WAIT_S = 15.0
WATCH_INTERVAL_S = 1.0
MAX_WATCH_BYTES = 16 * 1024 * 1024  # A planner file larger than this is not hashed every second or run.


class JobError(ValueError):
    """The run request is not acceptable."""


class Busy(RuntimeError):
    """Another job is still running."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _warn(message):
    """Last-resort note on stderr for trouble in a background thread; never raises itself."""
    try:
        print(f'raceplan: {message}', file=sys.stderr, flush=True)
    except Exception:
        pass


def _taskkill():
    """taskkill from the system folder by full path: a bare name is searched in the current folder first."""
    import ctypes
    buffer = ctypes.create_unicode_buffer(260)
    if not ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)):
        raise OSError('system folder not found')
    return os.path.join(buffer.value, 'taskkill.exe')


def _kill_tree(job):
    """Stop the workflow and everything a user planner started from it. On Windows the job object holds them all,
    even descendants whose parent already exited; elsewhere the process group does."""
    if job.winjob is not None and job.winjob.terminate():
        return
    process = job.process  # No job object (POSIX), or it could not be used: stop the tree another way.
    if process.poll() is not None:
        return
    try:
        if os.name == 'nt':
            subprocess.run([_taskkill(), '/F', '/T', '/PID', str(process.pid)], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)  # start_new_session made the workflow its group leader.
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        process.kill()


MISSING_MODULE = re.compile(r"No module named '([^']+)'")


def list_scenarios(folder):
    """Scenario YAML files under folder that load as scenarios (map YAML files and broken files are skipped).
    Files reached through a link that leaves the folder are not offered. Top-level files come first."""
    found = []
    for path in sorted(folder.rglob('*.yaml'), key=lambda item: (len(item.relative_to(folder).parts), item.as_posix())):
        if not path.is_file() or folder not in path.resolve().parents:
            continue
        try:
            scenario = load_scenario(path)
        except Exception:  # Anything that is not a valid scenario is simply not offered.
            continue
        found.append({'id': path.relative_to(folder).as_posix(), 'name': scenario.name,
                      'simulation_seed': scenario.simulation_seed})
    return found


def _slug(text):
    return re.sub(r'[^A-Za-z0-9_-]+', '-', text).strip('-_')[:48]


def run_slug(folder, scenario):
    """Readable part of a new run folder name: the scenario's own name, or its folder and file name when the name is
    missing, not ASCII or only the file name again (q0.yaml in two folders must not look the same). The folder is the
    real one even when the scenario is given as a bare file name next to it, as `raceplan-gui watch` does."""
    path = Path(scenario)
    try:
        name = load_scenario(Path(folder) / scenario).name or ''
    except Exception:  # Validated before a run starts; a name is a convenience, never a reason to fail.
        name = ''
    slug = _slug(name) if name.strip() != path.stem else ''
    parents = path.parent.parts or (Path(folder).resolve().name,)
    return slug or _slug('-'.join((*parents, path.stem))) or 'run'


def runs_slug(folder, scenarios):
    """Run folder name part for one or several scenarios: the first one's, then how many more (ASCII)."""
    first = run_slug(folder, scenarios[0])
    return first if len(scenarios) == 1 else f'{first[:40]}-plus{len(scenarios) - 1}'


def case_ids(scenarios):
    """Suite case ids for scenario paths (relative to the scenarios folder): safe, unique ignoring case and not a
    Windows reserved name, which is what raceplan.suite requires; readable from the path, numbered when they clash."""
    ids, used = [], set()
    for item in scenarios:
        base = _slug('-'.join(Path(item).with_suffix('').parts)) or 'case'
        if base.casefold() in RESERVED_IDS:
            base += '-case'
        name, index = base, 2
        while name.casefold() in used:
            name, index = f'{base}-{index}', index + 1
        used.add(name.casefold())
        ids.append(name)
    return ids


def _workflow_progress(path):
    try:
        state = json.loads(path.read_bytes().decode('utf-8'))
        error = state.get('error') if isinstance(state.get('error'), dict) else {}
        return {'status': state.get('status'), 'current_phase': state.get('current_phase'),
                'failed_phase': state.get('failed_phase'),
                'phases': {name: phase.get('status') for name, phase in state.get('phases', {}).items()},
                'error': {'type': error.get('type'), 'message': error.get('message')} if error else None}
    except (OSError, ValueError, AttributeError):
        return None  # Not written yet, mid-write or damaged; the next poll reads it again.


def _suite_progress(folder):
    """Where a suite run is: its status, case counts by status, the running case and the failed cases with why."""
    try:
        state = json.loads((folder / 'suite.json').read_bytes().decode('utf-8'))
        cases = state['cases']
        order = list(cases)
        current = next((case_id for case_id, record in cases.items() if record.get('status') == 'running'), None)
        failed = [{'case_id': case_id, 'failed_phase': record.get('failed_phase'),
                   'message': (record.get('error') or {}).get('message', '')}
                  for case_id, record in cases.items() if record.get('status') == 'failed']
        return {'status': state.get('status'), 'phase': state.get('phase'), 'total': len(order),
                'counts': dict(Counter(record.get('status') for record in cases.values())),
                'current': current, 'current_index': order.index(current) + 1 if current else None,
                'coverage': state.get('coverage'), 'failed': failed[:8]}
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return None


def _saved_status(job):
    """'complete' when the job's own state file says its comparison finished (a suite: also wrote its totals)."""
    name = 'suite.json' if job.spec['kind'] == 'suite' else 'workflow.json'
    try:
        state = json.loads((job.output / name).read_bytes().decode('utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict):
        return None
    done = state.get('status') == 'complete' and (name == 'workflow.json' or state.get('phase') == 'complete')
    return 'complete' if done else None


def _suite_versions(folder):
    """Planner file versions of a finished suite's completed cases against the suite's own record (see
    suite_view.planner_versions); None when the files to compare are not there."""
    try:
        state = json.loads((folder / 'suite.json').read_bytes().decode('utf-8'))
        provenance = json.loads((folder / 'provenance.json').read_bytes().decode('utf-8'))
        manifests = [(case_id, json.loads((folder / 'cases' / case_id / 'comparison_manifest.json').read_bytes()
                                          .decode('utf-8')))
                     for case_id, record in state['cases'].items() if record.get('status') == 'complete']
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None
    return suite_view.planner_versions(provenance, manifests)


def _note_watch_run(job):
    """Keep which watch run made this folder next to the runs (gui-runs/.run-meta/<run>.json), outside the engine's
    output, so the run list can show it later. The note carries the hash of the run's final state file, so a folder
    replaced or rewritten later is not shown with this run number. Only for a run that saved its state; a failure is
    noted, not fatal."""
    state = next((job.output / name for name in ('suite.json', 'workflow.json') if (job.output / name).is_file()), None)
    if state is None:
        return
    folder = job.output.parent / '.run-meta'
    try:
        note = {'schema_version': 1, 'run': job.output.name, 'state_sha256': hashlib.sha256(state.read_bytes()).hexdigest(),
                'watch_session': job.owner.session, 'watch_run': job.watch_run, 'trigger': job.trigger}
        folder.mkdir(exist_ok=True)
        if folder.resolve() != job.output.parent.resolve() / '.run-meta':
            raise OSError(f'{folder} leads outside the runs folder')  # Never write through a link elsewhere.
        workflow._save_state(folder / f'{job.output.name}.json', note)
    except OSError as exc:
        job.record = '; '.join(filter(None, [job.record, f'could not note the watch run ({exc})']))


def _rewrite_running(path, change):
    """Apply change to a saved state that still says running and save it atomically. Returns None when done or when
    there is nothing to correct, 'missing' when the file does not exist, else the last error."""
    error = None
    for attempt in range(5):
        try:
            state = json.loads(path.read_bytes().decode('utf-8'))
            if not isinstance(state, dict) or state.get('status') != 'running':
                return None
            change(state)
            workflow._save_state(path, state)
            return None
        except FileNotFoundError:
            return 'missing'
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            error = exc
            time.sleep(0.1 * (attempt + 1))  # A reader may briefly hold the file on Windows; try again.
    return str(error)


def _custom_spec(text):
    if not isinstance(text, str) or not text.strip():
        raise JobError('each user planner must be FILE.py:CLASS')
    filename, separator, classname = text.strip().rpartition(':')
    if not separator or not filename or not classname.isidentifier():
        raise JobError(f'user planner must be FILE.py:CLASS: {text}')
    if filename.startswith(('\\\\', '//')):
        raise JobError('user planner files must be on this computer, not a network share')
    path = Path(filename).expanduser().resolve()
    if path.suffix.lower() != '.py' or not path.is_file():
        raise JobError(f'user planner file not found or not Python: {path}')
    return f'{path}:{classname}'


class Job:
    def __init__(self, job_id, spec, output, run_id, command, timeout_s, trigger='start', watch_run=None):
        self.id, self.spec, self.output, self.run_id, self.command = job_id, spec, output, run_id, command
        self.timeout_s, self.trigger, self.watch_run = timeout_s, trigger, watch_run
        self.owner, self.record = None, None  # The watch that started it; why a stop could not be saved, if so.
        self.status = 'running'
        self.exit_code = None
        self.created_at, self.finished_at = _now(), None
        self.started = time.monotonic()
        self.elapsed_s = None
        self.log = deque(maxlen=LOG_LINES)
        self.cancel_requested, self.stop_note = False, None
        self.process = self.reader = self.waiter = self.winjob = None
        self.versions = None  # A finished suite: did each case run the planner files the suite recorded?

    def snapshot(self, lock):
        with lock:
            log, status, exit_code, finished_at = list(self.log), self.status, self.exit_code, self.finished_at
            elapsed = self.elapsed_s if self.elapsed_s is not None else time.monotonic() - self.started
        suite_state = _suite_progress(self.output) if self.spec['kind'] == 'suite' else None
        if self.spec['kind'] == 'suite':  # The phases shown are the running case's.
            current = suite_state and suite_state['current']
            workflow_state = _workflow_progress(self.output / 'cases' / current / 'workflow.json') if current else None
        else:
            workflow_state = _workflow_progress(self.output / 'workflow.json')
        # Only a failed run's last import error is its cause; a planner may log optional imports that failed earlier.
        missing = None if status in ('running', 'complete') else next(
            (found[1] for line in reversed(log) if (found := MISSING_MODULE.search(line))), None)
        return {'id': self.id, 'status': status, 'exit_code': exit_code, 'created_at': self.created_at,
                'finished_at': finished_at, 'elapsed_s': round(elapsed, 2), 'timeout_s': self.timeout_s,
                'run_id': self.run_id, 'trigger': self.trigger, 'watch_run': self.watch_run, **self.spec,
                'workflow': workflow_state, 'suite': suite_state, 'record': self.record, 'missing_module': missing,
                'planner_versions': self.versions, 'log': log}


def _fingerprint(paths, cache):
    """Content identity of the watched files, re-hashed only when size, time or inode changed. A None mark is a file
    that is missing, unreadable or refused; the returned problem says why a present file is refused."""
    marks, problem = [], None
    for path in paths:
        try:
            info = path.stat()
            if hasattr(os, 'getuid') and info.st_uid != os.getuid():
                problem = f'{path.name} is owned by another user now; not run until it is yours again'
                marks.append(None)
                continue
            if info.st_size > MAX_WATCH_BYTES:
                problem = f'{path.name} is larger than {MAX_WATCH_BYTES // 2**20} MiB; not run'
                marks.append(None)
                continue
            key = (info.st_size, info.st_mtime_ns, info.st_ino)
            if path not in cache or cache[path][0] != key:
                digest = hashlib.sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1 << 20), b''):
                        digest.update(chunk)
                cache[path] = (key, digest.hexdigest())
            marks.append(cache[path][1])
        except OSError:
            marks.append(None)
    return tuple(marks), problem


class Watch:
    """Re-run one comparison when a user planner file changes. A change counts once the file content has been the
    same for two polls in a row, so a half-written save never starts a run; a running watch run is cancelled first."""

    def __init__(self, spec, files, interval_s):
        self.spec, self.files, self.interval_s = spec, files, interval_s
        self.paths = None  # The scenario files the watch was started on; every rerun must use the same ones.
        self.session = secrets.token_hex(4)  # Tells this watch's runs apart from another watch's run 1, 2, ...
        self.active, self.runs, self.missing, self.blocked, self.error = True, 0, False, None, None
        self.started_at, self.last_change = _now(), None
        self.stop_event = threading.Event()
        self.cache = {}
        self.thread = None

    def snapshot(self):
        return {'active': self.active, 'files': [str(path) for path in self.files], 'runs': self.runs,
                'started_at': self.started_at, 'last_change': self.last_change, 'missing': self.missing,
                'blocked': self.blocked, 'error': self.error, 'interval_s': self.interval_s, **self.spec}


class Jobs:
    def __init__(self, root, scenarios, timeout_s=900.0, cwd=None, watch_interval_s=WATCH_INTERVAL_S, on_finish=None,
                 allowed=None):
        """allowed: scenario ids (relative to scenarios) to accept instead of listing the folder, for raceplan-watch,
        which is given its scenario files one by one and must not search the folder they share."""
        self.root, self.scenarios = Path(root).resolve(), Path(scenarios).resolve()
        self.timeout_s, self.cwd = float(timeout_s), Path(cwd or Path.cwd()).resolve()
        self.watch_interval_s, self.on_finish = float(watch_interval_s), on_finish
        self.allowed = None if allowed is None else list(allowed)
        self.lock = threading.Lock()
        self.jobs, self.current, self.watcher, self.closed = {}, None, None, False
        self.preparing = False  # One start at a time may read maps and hash inputs; others are refused meanwhile.

    def options(self):
        current = self.current.snapshot(self.lock) if self.current else None
        with self.lock:
            watch = self.watcher.snapshot() if self.watcher else None
        return {'enabled': True, 'reason': None, 'scenarios': list_scenarios(self.scenarios),
                'planners': list(experiment.PLANNER_FACTORIES), 'timeout_s': self.timeout_s,
                'output_folder': OUTPUT_FOLDER, 'current_job': current, 'watch': watch, 'noise_fields': list(NOISE_FIELDS),
                'limits': {'scenarios': MAX_CASES, 'seeds': MAX_SEEDS, 'scenario_seeds': MAX_CASE_SEEDS,
                           'episodes': MAX_EPISODES, 'user_planners': MAX_CUSTOM_PLANNERS}}

    def validate(self, body):
        """Check types before using values as set members or dict keys, so odd JSON is a 400 and never a crash.
        One scenario without noise runs as before (raceplan.workflow); several scenarios or any noise run as a suite."""
        if not isinstance(body, dict):
            raise JobError('request must be a JSON object')
        unknown = set(body) - FIELDS
        if unknown:
            raise JobError(f'unknown fields: {", ".join(sorted(unknown))}')
        if ('scenario' in body) == ('scenarios' in body):
            raise JobError('give either scenario or scenarios')
        scenarios = [body['scenario']] if 'scenario' in body else body['scenarios']
        listed = self.allowed if self.allowed is not None else {item['id'] for item in list_scenarios(self.scenarios)}
        if (not isinstance(scenarios, list) or not 1 <= len(scenarios) <= MAX_CASES
                or not all(isinstance(item, str) for item in scenarios) or len(set(scenarios)) != len(scenarios)
                or any(item not in listed for item in scenarios)):
            raise JobError(f'scenarios must be 1-{MAX_CASES} different listed scenarios')
        planners = body.get('planners')
        if (not isinstance(planners, list) or not planners or not all(isinstance(name, str) for name in planners)
                or len(set(planners)) != len(planners) or any(name not in experiment.PLANNER_FACTORIES for name in planners)):
            raise JobError(f'planners must be unique names from: {", ".join(experiment.PLANNER_FACTORIES)}')
        custom = body.get('custom_planners', [])
        if not isinstance(custom, list) or len(custom) > MAX_CUSTOM_PLANNERS:
            raise JobError(f'at most {MAX_CUSTOM_PLANNERS} user planners')
        custom = [_custom_spec(text) for text in custom]
        if len(set(custom)) != len(custom):
            raise JobError('user planners must be unique')
        if custom and body.get('trust_user_code') is not True:
            raise JobError('running user planner files needs trust_user_code: true (their code runs on this computer)')
        seeds = body.get('seeds')
        if (not isinstance(seeds, list) or not 1 <= len(seeds) <= MAX_SEEDS
                or any(type(seed) is not int or not 0 <= seed <= SEED_LIMIT for seed in seeds) or len(set(seeds)) != len(seeds)):
            raise JobError(f'seeds must be 1-{MAX_SEEDS} unique integers from 0 to {SEED_LIMIT}')
        baseline = body.get('baseline')
        if baseline is not None and (not isinstance(baseline, str) or baseline not in planners):
            raise JobError('baseline must be one of the selected built-in planners')
        noise = body.get('noise', {})
        if not isinstance(noise, dict) or set(noise) - set(NOISE_FIELDS):
            raise JobError(f'noise may only set: {", ".join(NOISE_FIELDS)}')
        values = {}
        for name in NOISE_FIELDS:
            value = noise.get(name, 0)
            try:
                ok = not isinstance(value, bool) and isinstance(value, (int, float)) and isfinite(value) and value >= 0
            except OverflowError:
                ok = False
            if not ok:
                raise JobError(f'noise {name} must be a finite number of at least 0')
            values[name] = float(value)
        pairs = len(scenarios) * len(seeds)
        if pairs > MAX_CASE_SEEDS or pairs * (len(planners) + len(custom)) > MAX_EPISODES:
            raise JobError(f'too large: scenarios x seeds must be at most {MAX_CASE_SEEDS} and scenarios x seeds x '
                           f'planners at most {MAX_EPISODES} episodes (asked {pairs} and {pairs * (len(planners) + len(custom))})')
        self._scenario_paths(scenarios)
        kind = 'suite' if len(scenarios) > 1 or any(values.values()) else 'workflow'
        return {'kind': kind, 'scenario': scenarios[0] if len(scenarios) == 1 else None, 'scenarios': scenarios,
                'planners': planners, 'custom_planners': custom, 'seeds': seeds, 'baseline': baseline, 'noise': values}

    def _scenario_paths(self, scenarios):
        """The files the ids name, checked again on every launch (a watch reruns long after its request was listed):
        inside the scenarios folder after following links, and different files even through aliases."""
        paths = [(self.scenarios / item).resolve() for item in scenarios]
        if any(self.scenarios not in path.parents or not path.is_file() for path in paths) or len(set(paths)) != len(paths):
            raise JobError('scenarios must be different files inside the scenarios folder')
        return paths

    def _output(self, slug):
        folder = self.root / OUTPUT_FOLDER
        try:
            folder.mkdir(exist_ok=True)
            probe = folder / f'.write-check-{secrets.token_hex(4)}'
            probe.mkdir()
            probe.rmdir()
        except OSError as exc:
            raise OSError(f'cannot write new runs under {folder} ({exc.strerror or exc}); open the explorer on another '
                          'results folder (RacePlan.exe FOLDER, raceplan-gui FOLDER) or give watch --output-root FOLDER') from exc
        # Seconds plus a random tag: raceplan-watch and the explorer may start runs in the same folder in the same second.
        stem = f'{datetime.now():%Y%m%d-%H%M%S}-{slug}-{secrets.token_hex(2)}'
        for index in range(1, 1000):
            output = folder / (stem if index == 1 else f'{stem}-{index}')
            if not output.exists():
                return output
        raise JobError('no free output folder name')

    def _suite_config(self, spec):
        """Write the suite config of one run (raceplan.suite's own format, absolute paths) next to the runs and check it
        with suite.load_config, which reads and hashes the inputs but runs no planner code. A config the suite would
        refuse is a request error, before any process starts. Done outside the jobs lock (it reads maps); the file is
        renamed after the run folder once that is chosen."""
        planners = spec['planners']
        config = {'version': 1,
                  'cases': [{'id': case_id, 'scenario': str(path)}
                            for case_id, path in zip(case_ids(spec['scenarios']), self._scenario_paths(spec['scenarios']))],
                  'planners': planners, 'custom_planners': spec['custom_planners'], 'simulation_seeds': spec['seeds'],
                  'noise': spec['noise'], 'baseline': spec['baseline'] or ('astar' if 'astar' in planners else planners[0])}
        folder = self.root / OUTPUT_FOLDER / SUITE_INPUTS
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f'pending-{secrets.token_hex(6)}.yaml'
        with path.open('x', encoding='utf-8') as stream:
            yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)
        try:
            suite.load_config(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            path.unlink(missing_ok=True)
            raise JobError(f'the suite would not accept this run: {exc}') from exc
        return path

    def start(self, body):
        return self._launch(self.validate(body))

    def _launch(self, spec, trigger='start', watch=None):
        with self.lock:
            self._refuse_if_busy(watch)  # Cheap refusals first; checked again below before anything starts.
            if self.preparing:
                raise Busy('another comparison is being prepared')
            self.preparing = True
        pending = None
        try:
            paths = self._scenario_paths(spec['scenarios'])
            if watch is not None and watch.paths is not None and paths != watch.paths:
                raise JobError('a scenario file of this watch now points somewhere else; start the watch again')
            slug = runs_slug(self.scenarios, spec['scenarios'])  # Reads the scenario names; outside the lock.
            pending = self._suite_config(spec) if spec['kind'] == 'suite' else None
            return self._start_process(spec, trigger, watch, pending, paths, slug)
        finally:
            if pending is not None:
                pending.unlink(missing_ok=True)  # Renamed when the run started; left only when it did not.
            with self.lock:
                self.preparing = False

    def _refuse_if_busy(self, watch):
        """Called with the lock held."""
        if self.closed:
            raise Busy('the explorer is closing')
        if watch is None and self.watcher is not None and self.watcher.active:
            raise Busy('a watch is running; stop it to start a single comparison')
        if watch is not None and not watch.active:
            raise Busy('the watch was stopped')  # "watch 끄기" pressed between the change and this launch.
        if self.current is not None and self.current.status == 'running':
            raise Busy('another comparison is still running')

    def _start_process(self, spec, trigger, watch, pending, paths, slug):
        with self.lock:
            self._refuse_if_busy(watch)
            output = self._output(slug)
            if pending is not None:
                config = pending.rename(pending.with_name(f'{output.name}.yaml'))
                args = [SUITE, str(config), '--output-dir', str(output)]
            else:
                args = [str(paths[0]), '--output-dir', str(output), '--planners', *spec['planners'],
                        *(f'--custom-planner={item}' for item in spec['custom_planners']),
                        '--simulation-seeds', *map(str, spec['seeds'])]
                if spec['baseline']:
                    args += ['--baseline', spec['baseline']]
            command = workflow_command([*args, START_SIGNAL])
            if watch is not None:
                watch.runs += 1
            job = Job(secrets.token_hex(8), spec, output, output.relative_to(self.root).as_posix(), command, self.timeout_s,
                      trigger, watch.runs if watch is not None else None)
            job.owner = watch
            # No console of its own (output is piped), and Ctrl+C in the explorer's window is not delivered to it.
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            job.process = subprocess.Popen(command, cwd=worker_folder(self.cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != 'nt',
                                           env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'})
            self.jobs[job.id], self.current = job, job
            finished = [key for key, item in self.jobs.items() if item.status != 'running']
            for key in finished[:-KEEP_FINISHED]:
                del self.jobs[key]
            job.reader = threading.Thread(target=self._read, args=(job,), daemon=True)
            job.waiter = threading.Thread(target=self._wait, args=(job,), daemon=True)
            # Started under the lock: shutdown() then always finds a published job with threads it can join.
            job.reader.start()
            job.waiter.start()
            # Last: only a registered job, which shutdown() will find and stop, is allowed to load a planner.
            self._contain_and_start(job)
        return job.snapshot(self.lock)

    def watch(self, body, on_event=None):
        """Run now, then again whenever a user planner file changes, until stop_watch()."""
        spec = self.validate(body)
        if not spec['custom_planners']:
            raise JobError('watch needs at least one user planner file to watch')
        files = list(dict.fromkeys(Path(item.rpartition(':')[0]) for item in spec['custom_planners']))  # One file, many classes.
        with self.lock:
            if self.watcher is not None and self.watcher.active:
                raise Busy('a watch is already running')
            if self.current is not None and self.current.status == 'running':
                raise Busy('another comparison is still running')
            watch = self.watcher = Watch(spec, files, self.watch_interval_s)
            watch.paths = self._scenario_paths(spec['scenarios'])
        baseline, refused = _fingerprint(files, watch.cache)  # Before the first run, so a save during it still reruns.
        if refused or None in baseline:
            with self.lock:
                watch.active = False
            raise JobError(refused or 'a watched planner file is missing or unreadable')
        try:
            job = self._launch(spec, 'start', watch)
        except Exception:
            watch.active = False
            raise
        thread = threading.Thread(target=self._watch_loop, args=(watch, baseline, on_event), daemon=True)
        thread.start()
        watch.thread = thread  # Published only once started, so stop_watch() never joins a thread that has not begun.
        return {'watch': watch.snapshot(), 'job': job}

    def _watch_loop(self, watch, last, on_event):
        try:
            self._watch_changes(watch, last, on_event)
        except Exception as exc:  # A dead watch must say so instead of showing "watching" forever.
            with self.lock:
                watch.error, watch.active = f'watch stopped: {type(exc).__name__}: {exc}', False
            watch.stop_event.set()

    def _watch_changes(self, watch, last, on_event):
        pending = None
        while not watch.stop_event.wait(watch.interval_s):
            now, watch.blocked = _fingerprint(watch.files, watch.cache)
            watch.missing = None in now
            if now == last or watch.missing:
                pending = None  # Unchanged, or mid-save / deleted / refused: wait for a readable, stable file.
                continue
            if now != pending:
                pending = now  # Changed: confirm on the next poll that the content has settled.
                continue
            last, pending = now, None
            watch.last_change = _now()
            with self.lock:  # Only this watch's own run is replaced, and only while this watch is still on.
                if not watch.active:
                    break
                current = self.current
                running = current if current is not None and current.status == 'running' and current.owner is watch else None
            if running is not None:
                # The old code's result is no longer what the user is looking at.
                self.cancel(running.id, 'stopped by watch: the planner file changed')
                running.waiter.join(timeout=FINISH_WAIT_S)
            if watch.stop_event.is_set():
                break
            try:
                job = self._launch(watch.spec, 'change', watch)
                watch.error = None
            except (OSError, JobError, Busy) as exc:
                watch.error, job = str(exc), None
            if on_event is not None:
                try:
                    on_event('change', job, running)
                except Exception as exc:  # Reporting trouble (closed pipe, console encoding) must not stop watching.
                    _warn(f'could not report a watch change: {exc!r}')

    def stop_watch(self):
        with self.lock:
            watch = self.watcher
            if watch is None or not watch.active:
                return watch.snapshot() if watch else None
            watch.active = False
            watch.stop_event.set()
        if watch.thread is not None and watch.thread is not threading.current_thread():
            watch.thread.join(timeout=FINISH_WAIT_S)
        return watch.snapshot()

    def _read(self, job):
        for raw in iter(lambda: job.process.stdout.readline(READ_LIMIT), b''):
            line = raw.decode('utf-8', errors='replace').rstrip('\r\n')
            with self.lock:
                job.log.append(line[:LOG_LINE_CHARS])

    def _wait(self, job):
        timed_out = False
        try:
            job.process.wait(timeout=job.timeout_s)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(job)
            job.process.wait()
        code = job.process.returncode
        if job.winjob is not None:
            job.winjob.close()  # Stops anything the planner left running, which would also keep the log pipe open.
        # A comparison that finished on its own is complete even if a cancel arrived at the same moment: by its exit
        # code, or by its saved state when it was killed right after saving that it completed.
        status = 'complete' if code == 0 else 'cancelled' if job.cancel_requested else 'timeout' if timed_out else 'failed'
        if status in ('cancelled', 'timeout') and _saved_status(job) == 'complete':
            status = 'complete'
        try:
            job.reader.join(timeout=5)  # The last lines (workflow=..., errors) belong to the finished job.
            if status in ('cancelled', 'timeout'):
                self._record_stop(job, status)  # Before publishing, so a finished job never shows a stale state file.
            if job.spec['kind'] == 'suite':
                job.versions = _suite_versions(job.output)
            if job.owner is not None:
                _note_watch_run(job)
        finally:
            with self.lock:
                job.exit_code = code
                job.elapsed_s = time.monotonic() - job.started
                job.finished_at = _now()
                job.status = status
        if self.on_finish is not None:
            try:
                self.on_finish(job.snapshot(self.lock))
            except Exception as exc:  # A reporting callback must never keep a job from finishing, but must not vanish.
                _warn(f'could not report job {job.id} ({job.status}): {exc!r}')

    @staticmethod
    def _record_stop(job, status):
        """A killed comparison cannot write its own failure, so record it the way workflow.py records an interrupt.
        Only state files of the folder this job created are touched, and only while they still say running. A suite
        becomes interrupted: its running case failed (with that case's workflow.json), cases not started not_run,
        coverage recounted; finished cases and their files stay as they are, and no totals are written."""
        message = (f'stopped after the {job.timeout_s:g} s time limit' if status == 'timeout'
                   else job.stop_note or 'stopped by the user from the explorer')
        error = {'type': 'Timeout' if status == 'timeout' else 'Cancelled', 'message': message,
                 'exit_code': job.process.returncode, 'control_exception': True}

        def stop_workflow(state):
            phase = state.get('current_phase')
            if isinstance(state.get('phases'), dict) and isinstance(state['phases'].get(phase), dict):
                state['phases'][phase]['status'] = 'failed'
            state.update(status='failed', failed_phase=phase, finished_at_utc=_now(), error=error)

        notes = []

        def stop_suite(state):
            for case_id, record in state['cases'].items():
                if record.get('status') == 'running':
                    problem = _rewrite_running(job.output / 'cases' / case_id / 'workflow.json', stop_workflow)
                    if problem not in (None, 'missing'):
                        notes.append(f'could not record the stop in cases/{case_id}/workflow.json ({problem})')
                    record.update(status='failed', failed_phase='invocation', error=error, finished_at_utc=_now())
                elif record.get('status') == 'pending':
                    record['status'] = 'not_run'
            state.update(status='interrupted', finished_at_utc=_now(), error=error, coverage=suite._coverage(state))

        name = 'suite.json' if job.spec['kind'] == 'suite' else 'workflow.json'
        problem = _rewrite_running(job.output / name, stop_suite if name == 'suite.json' else stop_workflow)
        if problem == 'missing' and name == 'suite.json' and job.output.is_dir():
            # The suite had made its folder but not yet its state: record what was asked and that nothing ran.
            per_case = (len(job.spec['planners']) + len(job.spec['custom_planners'])) * len(job.spec['seeds'])
            state = {'schema_version': 1, 'status': 'interrupted', 'phase': 'cases', 'created_at_utc': _now(),
                     'finished_at_utc': _now(), 'error': error,
                     'cases': {case_id: {'case_id': case_id, 'status': 'not_run', 'expected_episode_count': per_case,
                                         'raw_episode_count': 0, 'included_episode_count': 0}
                               for case_id in case_ids(job.spec['scenarios'])}}
            state['coverage'] = suite._coverage(state)
            try:
                workflow._save_state(job.output / 'suite.json', state)
                problem = None
                notes.append('stopped before the suite saved its state; recorded as interrupted with no case run')
            except OSError as exc:
                problem = str(exc)
        if problem == 'missing':
            # Stopped before anything was saved: there is no saved run to correct or to list.
            notes.append(f'stopped before the {"suite" if name == "suite.json" else "workflow"} saved its state; '
                         'nothing was saved for this run')
        elif problem:
            notes.append(f'could not record the stop in {name} ({problem}); the saved run may still say running')
        job.record = '; '.join(notes) or None

    def get(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job.snapshot(self.lock)

    def cancel(self, job_id, note=None):
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        with self.lock:
            stop = job.status == 'running' and job.process.poll() is None
            if stop:
                job.cancel_requested, job.stop_note = True, note
        if stop:
            _kill_tree(job)
        return job.snapshot(self.lock)

    @staticmethod
    def _contain_and_start(job):
        """On Windows put the worker in its own kill-on-close job object, then let it start (see workflow_runner).
        If containment fails nothing is loaded: the worker is stopped and the job ends as failed with the reason."""
        try:
            if os.name == 'nt':
                from raceplan.gui.winjob import KillOnCloseJob
                job.winjob = KillOnCloseJob()
                job.winjob.assign(job.process)
        except OSError as exc:
            job.record = f'not started: could not contain the comparison in a Windows job object ({exc})'
            job.process.kill()
            if job.winjob is not None:
                job.winjob.close()
                job.winjob = None
            return
        try:
            job.process.stdin.write(b'start\n')
            job.process.stdin.close()
        except OSError:
            pass  # The worker already ended; its exit code and log say why.

    def shutdown(self, deadline_s=None):
        """Stop watching and stop running jobs, waiting until their stop is recorded, so closing the explorer leaves
        no 'running' run behind. Nothing new starts once this begins. Workers are stopped before anything is waited
        for, and deadline_s bounds the whole wait (a closing console window gives only a few seconds); without it
        each job gets FINISH_WAIT_S."""
        end = None if deadline_s is None else time.monotonic() + deadline_s

        def left():
            return FINISH_WAIT_S if end is None else max(0.0, end - time.monotonic())
        with self.lock:
            self.closed = True
            watch = self.watcher
            if watch is not None and watch.active:
                watch.active = False
                watch.stop_event.set()
            running = [job for job in self.jobs.values() if job.status == 'running']
            for job in running:
                job.cancel_requested, job.stop_note = True, 'stopped because the explorer or raceplan-watch was closed'
        for job in running:
            _kill_tree(job)
        for job in running:
            job.waiter.join(timeout=left())
        if watch is not None and watch.thread is not None and watch.thread is not threading.current_thread():
            watch.thread.join(timeout=left())
