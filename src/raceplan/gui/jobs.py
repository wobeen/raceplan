"""Run comparisons for the explorer in a separate process, never inside the server process.

A job is one ``raceplan.workflow`` call (through raceplan.gui.workflow_runner, which only makes its state saves
tolerate the explorer reading workflow.json on Windows). Requests are validated against what the server lists
(scenarios, built-in planners) before anything starts; user planner files are only checked for existence here and are
loaded, and therefore executed, by the workflow process. One job runs at a time, with a time limit and cancellation;
stopping kills the whole process tree and records the stop in the job's own workflow.json the way workflow.py records
an interrupt.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import threading
import time

from raceplan import experiment, workflow
from raceplan.common import load_scenario

OUTPUT_FOLDER = 'gui-runs'
LOG_LINES = 400
LOG_LINE_CHARS = 2000
READ_LIMIT = 64 * 1024  # One read never holds more than this, even if a planner prints without newlines.
KEEP_FINISHED = 20
MAX_CUSTOM_PLANNERS = 8
MAX_SEEDS = 50
SEED_LIMIT = 2**31 - 1
FIELDS = {'scenario', 'planners', 'custom_planners', 'seeds', 'baseline', 'trust_user_code'}
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


def _kill_tree(process):
    """Stop the workflow and anything a user planner started from it."""
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
        self.process = self.reader = self.waiter = None

    def snapshot(self, lock):
        with lock:
            log, status, exit_code, finished_at = list(self.log), self.status, self.exit_code, self.finished_at
            elapsed = self.elapsed_s if self.elapsed_s is not None else time.monotonic() - self.started
        workflow_state = None
        try:
            state = json.loads((self.output / 'workflow.json').read_bytes().decode('utf-8'))
            error = state.get('error') if isinstance(state.get('error'), dict) else {}
            workflow_state = {'status': state.get('status'), 'current_phase': state.get('current_phase'),
                              'failed_phase': state.get('failed_phase'),
                              'phases': {name: phase.get('status') for name, phase in state.get('phases', {}).items()},
                              'error': {'type': error.get('type'), 'message': error.get('message')} if error else None}
        except (OSError, ValueError, AttributeError):
            workflow_state = None  # Not written yet, mid-write or damaged; the next poll reads it again.
        return {'id': self.id, 'status': status, 'exit_code': exit_code, 'created_at': self.created_at,
                'finished_at': finished_at, 'elapsed_s': round(elapsed, 2), 'timeout_s': self.timeout_s,
                'run_id': self.run_id, 'trigger': self.trigger, 'watch_run': self.watch_run, **self.spec,
                'workflow': workflow_state, 'record': self.record, 'log': log}


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
    def __init__(self, root, scenarios, timeout_s=900.0, cwd=None, watch_interval_s=WATCH_INTERVAL_S, on_finish=None):
        self.root, self.scenarios = Path(root).resolve(), Path(scenarios).resolve()
        self.timeout_s, self.cwd = float(timeout_s), Path(cwd or Path.cwd()).resolve()
        self.watch_interval_s, self.on_finish = float(watch_interval_s), on_finish
        self.lock = threading.Lock()
        self.jobs, self.current, self.watcher, self.closed = {}, None, None, False

    def options(self):
        current = self.current.snapshot(self.lock) if self.current else None
        with self.lock:
            watch = self.watcher.snapshot() if self.watcher else None
        return {'enabled': True, 'reason': None, 'scenarios': list_scenarios(self.scenarios),
                'planners': list(experiment.PLANNER_FACTORIES), 'timeout_s': self.timeout_s,
                'output_folder': OUTPUT_FOLDER, 'current_job': current, 'watch': watch}

    def validate(self, body):
        """Check types before using values as set members or dict keys, so odd JSON is a 400 and never a crash."""
        if not isinstance(body, dict):
            raise JobError('request must be a JSON object')
        unknown = set(body) - FIELDS
        if unknown:
            raise JobError(f'unknown fields: {", ".join(sorted(unknown))}')
        scenario = body.get('scenario')
        if not isinstance(scenario, str) or scenario not in {item['id'] for item in list_scenarios(self.scenarios)}:
            raise JobError('scenario must be one of the listed scenarios')
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
        return {'scenario': scenario, 'planners': planners, 'custom_planners': custom, 'seeds': seeds, 'baseline': baseline}

    def _output(self, scenario):
        folder = self.root / OUTPUT_FOLDER
        folder.mkdir(exist_ok=True)
        # Seconds plus a random tag: raceplan-watch and the explorer may start runs in the same folder in the same second.
        stem = f'{datetime.now():%Y%m%d-%H%M%S}-{Path(scenario).stem}-{secrets.token_hex(2)}'
        for index in range(1, 1000):
            output = folder / (stem if index == 1 else f'{stem}-{index}')
            if not output.exists():
                return output
        raise JobError('no free output folder name')

    def start(self, body):
        return self._launch(self.validate(body))

    def _launch(self, spec, trigger='start', watch=None):
        with self.lock:
            if self.closed:
                raise Busy('the explorer is closing')
            if watch is None and self.watcher is not None and self.watcher.active:
                raise Busy('a watch is running; stop it to start a single comparison')
            if watch is not None and not watch.active:
                raise Busy('the watch was stopped')  # "watch 끄기" pressed between the change and this launch.
            if self.current is not None and self.current.status == 'running':
                raise Busy('another comparison is still running')
            output = self._output(spec['scenario'])
            # -P keeps the server's working folder off sys.path, so a stray yaml.py or numpy.py there is never imported.
            command = [sys.executable, '-P', '-m', 'raceplan.gui.workflow_runner', str(self.scenarios / spec['scenario']),
                       '--output-dir', str(output), '--planners', *spec['planners'],
                       *(f'--custom-planner={item}' for item in spec['custom_planners']),
                       '--simulation-seeds', *map(str, spec['seeds'])]
            if spec['baseline']:
                command += ['--baseline', spec['baseline']]
            if watch is not None:
                watch.runs += 1
            job = Job(secrets.token_hex(8), spec, output, output.relative_to(self.root).as_posix(), command, self.timeout_s,
                      trigger, watch.runs if watch is not None else None)
            job.owner = watch
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            job.process = subprocess.Popen(command, cwd=self.cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
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
        return job.snapshot(self.lock)

    def watch(self, body, on_event=None):
        """Run now, then again whenever a user planner file changes, until stop_watch()."""
        spec = self.validate(body)
        if not spec['custom_planners']:
            raise JobError('watch needs at least one user planner file to watch')
        files = [Path(item.rpartition(':')[0]) for item in spec['custom_planners']]
        with self.lock:
            if self.watcher is not None and self.watcher.active:
                raise Busy('a watch is already running')
            if self.current is not None and self.current.status == 'running':
                raise Busy('another comparison is still running')
            watch = self.watcher = Watch(spec, files, self.watch_interval_s)
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
        watch.thread = threading.Thread(target=self._watch_loop, args=(watch, baseline, on_event), daemon=True)
        watch.thread.start()
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
            _kill_tree(job.process)
            job.process.wait()
        code = job.process.returncode
        # A workflow that finished on its own is complete even if a cancel arrived at the same moment.
        status = 'complete' if code == 0 else 'cancelled' if job.cancel_requested else 'timeout' if timed_out else 'failed'
        try:
            job.reader.join(timeout=5)  # The last lines (workflow=..., errors) belong to the finished job.
            if status in ('cancelled', 'timeout'):
                self._record_stop(job, status)  # Before publishing, so a finished job never shows a stale state file.
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
        """A killed workflow cannot write its own failure, so record it the way workflow.py records an interrupt.
        Only the state file of the folder this job created is touched, and only while it still says running."""
        path = job.output / 'workflow.json'
        for attempt in range(5):
            try:
                state = json.loads(path.read_bytes().decode('utf-8'))
                if not isinstance(state, dict) or state.get('status') != 'running':
                    return
                phase = state.get('current_phase')
                if isinstance(state.get('phases'), dict) and isinstance(state['phases'].get(phase), dict):
                    state['phases'][phase]['status'] = 'failed'
                message = (f'stopped after the {job.timeout_s:g} s time limit' if status == 'timeout'
                           else job.stop_note or 'stopped by the user from the explorer')
                state.update(status='failed', failed_phase=phase, finished_at_utc=_now(),
                             error={'type': 'Timeout' if status == 'timeout' else 'Cancelled', 'message': message,
                                    'exit_code': job.process.returncode, 'control_exception': True})
                workflow._save_state(path, state)
                return
            except FileNotFoundError:
                # Stopped before the workflow saved anything: there is no saved run to correct or to list.
                job.record = 'stopped before the workflow saved its state; nothing was saved for this run'
                return
            except (OSError, ValueError) as exc:
                error = exc
                time.sleep(0.1 * (attempt + 1))  # A reader may briefly hold the file on Windows; try again.
        job.record = f'could not record the stop in workflow.json ({error}); the saved run may still say running'

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
            _kill_tree(job.process)
        return job.snapshot(self.lock)

    def shutdown(self):
        """Stop watching and stop running jobs, waiting until their stop is recorded, so closing the explorer leaves
        no 'running' run behind. Nothing new starts once this begins."""
        with self.lock:
            self.closed = True
        self.stop_watch()
        with self.lock:
            running = [job for job in self.jobs.values() if job.status == 'running']
            for job in running:
                job.cancel_requested, job.stop_note = True, 'stopped because the explorer or raceplan-watch was closed'
        for job in running:
            _kill_tree(job.process)
        for job in running:
            job.waiter.join(timeout=FINISH_WAIT_S)
