"""Re-run a comparison every time your planner file changes (raceplan-watch FILE.py:CLASS --scenario FILE.yaml).

Each run is the same separate raceplan.workflow process the explorer starts, saved as a new folder under
<output-root>/gui-runs, so raceplan-gui shows it too. A run that is still going when the file changes again is
stopped and recorded as cancelled. Loading a planner file executes its code: only watch files you trust.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from math import isfinite
from pathlib import Path
import signal
import sys
import time

from raceplan import experiment
from raceplan.common import load_scenario
from raceplan.gui.console import CLOSE_DEADLINE_S, on_console_close
from raceplan.gui.frozen import default_results, is_frozen
from raceplan.gui.jobs import Busy, JobError, Jobs


MIN_INTERVAL_S = 0.2  # Each check stats (and on change hashes) every watched file.


def _stop_on_signal(*_):
    raise KeyboardInterrupt


def _outcomes(root, run_id):
    """Reached / recorded per planner from the saved analysis, the same counts the explorer leaderboard shows."""
    path = Path(root) / run_id / 'analysis/episodes.csv'
    try:
        with path.open(newline='', encoding='utf-8-sig') as stream:
            rows = list(csv.DictReader(stream))
    except OSError:
        return ''
    total, reached = Counter(row['planner'] for row in rows), Counter(row['planner'] for row in rows if row['failure_class'] == 'reached')
    return ' · '.join(f'{name} {reached[name]}/{count} reached' for name, count in total.items())


def _reporter(root):
    def report(job):
        label = f'run {job["watch_run"]}' if job.get('watch_run') else 'run'
        line = f'{label}: {job["status"]} in {job["elapsed_s"]:.1f} s -> {Path(root) / job["run_id"]}'
        if job['status'] == 'complete':
            line += f'\n  {_outcomes(root, job["run_id"])}'
        else:
            error = (job.get('workflow') or {}).get('error') or {}
            if error:
                line += f'\n  {error.get("type")}: {error.get("message")}'
            line += ''.join(f'\n  | {text}' for text in job['log'][-8:])
            if job.get('missing_module'):
                line += f'\n  {missing_module_hint(job["missing_module"])}'
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
    parser.add_argument('--scenario', type=Path, required=True, help='scenario YAML to run')
    parser.add_argument('--planners', nargs='+', choices=tuple(experiment.PLANNER_FACTORIES), default=['astar'],
                        help='built-in planners to compare against (default: astar)')
    parser.add_argument('--seeds', nargs='+', type=int, help='simulation seeds (default: the scenario seed)')
    parser.add_argument('--baseline', help='analysis baseline among the built-in planners (default: astar or the first)')
    parser.add_argument('--output-root', type=Path, default=default_results(),
                        help='runs go to OUTPUT_ROOT/gui-runs (default: %(default)s)')
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between file checks')
    parser.add_argument('--timeout', type=float, default=900.0, help='seconds before one run is stopped')
    parser.add_argument('--once', action='store_true', help='run once and exit (exit code 0 only if it completes)')
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # A path or log line the console cannot encode must not end the watch.
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    parser = _parser()
    args = parser.parse_args(argv)
    scenario = args.scenario.resolve()
    if not scenario.is_file():
        parser.error(f'scenario not found: {args.scenario}')
    if not isfinite(args.interval) or args.interval < MIN_INTERVAL_S:
        parser.error(f'interval must be at least {MIN_INTERVAL_S:g} seconds')
    if not isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be a positive number of seconds')
    try:
        seeds = args.seeds if args.seeds is not None else [load_scenario(scenario).simulation_seed]
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    try:
        args.output_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        parser.error(f'cannot use {args.output_root} for results: {exc}; choose another folder with --output-root')
    root = args.output_root.resolve()
    report = _reporter(root)
    jobs = Jobs(root, scenario.parent, args.timeout, watch_interval_s=args.interval, on_finish=report)
    # Typing the file on the command line is the trust decision the explorer asks for with a checkbox.
    body = {'scenario': scenario.name, 'planners': args.planners, 'custom_planners': args.custom_planners,
            'seeds': seeds, 'baseline': args.baseline, 'trust_user_code': True}
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
