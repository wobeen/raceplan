"""Re-run a comparison every time your planner file changes (raceplan-watch FILE.py:CLASS --scenario FILE.yaml).

Each run is the same separate process the explorer starts (raceplan.workflow, or raceplan.suite when several
--scenario files or any noise are given), saved as a new folder under <output-root>/gui-runs, so raceplan-gui shows it
too. A run that is still going when the file changes again is stopped and recorded as cancelled. Loading a planner
file executes its code: only watch files you trust.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
import json
from math import isfinite
import os
from pathlib import Path
import signal
import sys
import time

from raceplan import experiment
from raceplan.common import load_scenario
from raceplan.gui.console import CLOSE_DEADLINE_S, on_console_close
from raceplan.gui.frozen import default_results, is_frozen
from raceplan.gui.jobs import NOISE_FIELDS, Busy, JobError, Jobs


MIN_INTERVAL_S = 0.2  # Each check stats (and on change hashes) every watched file.


def _stop_on_signal(*_):
    raise KeyboardInterrupt


def _outcomes(root, run_id):
    """Reached / recorded per planner from the saved analysis, the same counts the explorer leaderboard shows; for a
    suite, pooled over the cases its suite.json lists as complete (a case that failed later, e.g. while drawing its
    report, may have an analysis but is not part of the suite's totals and is not counted here either)."""
    folder = Path(root) / run_id
    if (folder / 'suite.json').is_file():
        try:
            cases = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))['cases']
        except (OSError, ValueError, KeyError):
            return 'suite.json could not be read'
        done = [case_id for case_id, record in cases.items() if record.get('status') == 'complete']
        paths = [folder / 'cases' / case_id / 'analysis/episodes.csv' for case_id in done]
    else:
        done, paths = None, [folder / 'analysis/episodes.csv']
    rows = []
    for path in paths:
        try:
            with path.open(newline='', encoding='utf-8-sig') as stream:
                rows += list(csv.DictReader(stream))
        except OSError:
            continue
    total, reached = Counter(row['planner'] for row in rows), Counter(row['planner'] for row in rows if row['failure_class'] == 'reached')
    text = ' · '.join(f'{name} {reached[name]}/{count} reached' for name, count in total.items())
    return text if done is None else f'{len(done)}/{len(cases)} case(s) complete: {text}'


def _reporter(root):
    def report(job):
        label = f'run {job["watch_run"]}' if job.get('watch_run') else 'run'
        line = f'{label}: {job["status"]} in {job["elapsed_s"]:.1f} s -> {Path(root) / job["run_id"]}'
        progress = job.get('suite') or {}
        if job['status'] == 'complete' or (progress.get('counts') or {}).get('complete'):
            line += f'\n  {_outcomes(root, job["run_id"])}'
        coverage = progress.get('coverage') or {}
        if coverage:
            line += (f'\n  cases: {coverage.get("completed_cases")} complete, {coverage.get("failed_cases")} failed, '
                     f'{coverage.get("not_run_cases")} not run; episodes {coverage.get("included_episode_count")}'
                     f'/{coverage.get("expected_episode_count")}')
        for item in (job.get('planner_versions') or {}).get('mismatches', []):
            line += (f'\n  warning: case {item["case"]} ran {item["planner"]} from another version of its file '
                     f'({item["ran"]}) than the suite recorded ({item["recorded"]}); it was saved during the run')
        if job['status'] != 'complete':
            line += ''.join(f'\n  {item["case_id"]}: {item["failed_phase"]}: {item["message"]}' for item in progress.get('failed', []))
            error = (job.get('workflow') or {}).get('error') or {}
            if error:
                line += f'\n  {error.get("type")}: {error.get("message")}'
            line += ''.join(f'\n  | {text}' for text in job['log'][-8:])
            if job.get('missing_module'):
                line += f'\n  {missing_module_hint(job["missing_module"])}'
        if job.get('record'):
            line += f'\n  {job["record"]}'  # e.g. stopped before anything was saved, or a stop that could not be recorded
        print(line, flush=True)
    return report


def missing_module_hint(name):
    if is_frozen():
        return (f'module {name!r} is not part of this RacePlan.exe (it ships RacePlan, NumPy, Pillow, PyYAML and the '
                'Python standard library); run your planner with a Python install of RacePlan that has it installed')
    return f'module {name!r} is not installed in this Python environment; install it there and run again'


def _parser():
    parser = argparse.ArgumentParser(prog='RacePlan.exe watch' if is_frozen() else None, description=__doc__, allow_abbrev=False)
    parser.add_argument('custom_planners', nargs='+', metavar='FILE.py:CLASS', help='your planner(s); their files are watched')
    parser.add_argument('--scenario', type=Path, action='append', required=True,
                        help='scenario YAML to run; give it several times to run them together as a suite')
    parser.add_argument('--planners', nargs='+', choices=tuple(experiment.PLANNER_FACTORIES), default=['astar'],
                        help='built-in planners to compare against (default: astar)')
    parser.add_argument('--seeds', nargs='+', type=int, help='simulation seeds (default: the scenario seed)')
    parser.add_argument('--baseline', help='analysis baseline among the built-in planners (default: astar or the first)')
    parser.add_argument('--output-root', type=Path, default=default_results(),
                        help='runs go to OUTPUT_ROOT/gui-runs (default: %(default)s)')
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between file checks')
    parser.add_argument('--timeout', type=float, default=900.0, help='seconds before one run is stopped')
    parser.add_argument('--once', action='store_true', help='run once and exit (exit code 0 only if it completes)')
    noise = parser.add_argument_group('noise (any value above 0 runs a suite; default 0 = no noise)')
    for name in NOISE_FIELDS:
        noise.add_argument('--' + name.replace('_', '-'), type=float, default=0.0, metavar='X')
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # A path or log line the console cannot encode must not end the watch.
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    parser = _parser()
    args = parser.parse_args(argv)
    scenarios = [path.resolve() for path in args.scenario]
    for given, path in zip(args.scenario, scenarios):
        if not path.is_file():
            parser.error(f'scenario not found: {given}')
    if not isfinite(args.interval) or args.interval < MIN_INTERVAL_S:
        parser.error(f'interval must be at least {MIN_INTERVAL_S:g} seconds')
    if not isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be a positive number of seconds')
    try:
        # Only the given files are accepted; their common folder is never searched for others.
        folder = Path(os.path.commonpath([path.parent for path in scenarios]))
    except ValueError:
        parser.error('the scenario files must be on one drive')
    try:
        defaults = {load_scenario(path).simulation_seed for path in scenarios}
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.seeds is None and len(defaults) > 1:
        parser.error(f'the scenarios have different own seeds ({", ".join(map(str, sorted(defaults)))}); give --seeds')
    seeds = args.seeds if args.seeds is not None else sorted(defaults)
    ids = [path.relative_to(folder).as_posix() for path in scenarios]
    try:
        args.output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        parser.error(f'cannot use {args.output_root} for results: {exc}; choose another folder with --output-root')
    root = args.output_root.resolve()
    report = _reporter(root)
    jobs = Jobs(root, folder, args.timeout, watch_interval_s=args.interval, on_finish=report, allowed=ids)
    # Typing the file on the command line is the trust decision the explorer asks for with a checkbox.
    body = {'scenarios': ids, 'planners': args.planners, 'custom_planners': args.custom_planners, 'seeds': seeds,
            'baseline': args.baseline, 'noise': {name: getattr(args, name) for name in NOISE_FIELDS},
            'trust_user_code': True}
    for name in ('SIGTERM', 'SIGHUP', 'SIGBREAK'):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _stop_on_signal)
    remove_close_handler = on_console_close(lambda: jobs.shutdown(deadline_s=CLOSE_DEADLINE_S))
    try:
        if args.once:
            job = jobs.jobs[jobs.start(body)['id']]
            while job.waiter.is_alive():
                job.waiter.join(timeout=0.5)  # Short joins keep Ctrl+C working on Windows.
            return 0 if job.status == 'complete' else 1

        def changed(kind, job, stopped):
            note = ' (stopped the previous run)' if stopped is not None else ''
            print(f'file changed{note}; ' + (f'run {job["watch_run"]} started' if job else f'not started: {jobs.watcher.error}'), flush=True)

        started = jobs.watch(body, on_event=changed)
        print(f'watching {", ".join(started["watch"]["files"])} (every {args.interval:g} s, Ctrl+C to stop)\nrun 1 started', flush=True)
        watch, blocked = jobs.watcher, None
        while watch.active:
            if watch.blocked != blocked:
                blocked = watch.blocked
                print(f'waiting: {blocked}' if blocked else 'file accepted again', flush=True)
            time.sleep(0.5)
        print(f'raceplan-watch: {watch.error}', file=sys.stderr, flush=True)
        return 1
    except (JobError, Busy) as exc:
        parser.error(str(exc))
    except OSError as exc:  # e.g. the results folder is read-only; the message says which folder and what to do.
        print(f'raceplan-watch: {exc}', file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('stopping...', file=sys.stderr, flush=True)
        return 130 if args.once else 0  # An interrupted --once run did not complete.
    finally:
        jobs.shutdown()
        remove_close_handler()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
