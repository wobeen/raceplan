"""Run a comparison, analyze saved artifacts, and render a PNG in one new folder."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import fields
from datetime import datetime, timezone
import json
from math import isfinite
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from time import perf_counter

import yaml

from raceplan import analyze, custom_report, experiment
from raceplan.common import load_occupancy_map, load_scenario
from raceplan.simulator import NoiseConfig


def _parser():
    # No abbreviations: --output belongs to the lower-level APIs, not this wrapper.
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output-dir', required=True, type=Path, help='new folder for all outputs')
    parser.add_argument('--planners', nargs='+', choices=tuple(experiment.PLANNER_FACTORIES),
                        default=list(experiment.PLANNER_FACTORIES))
    parser.add_argument('--custom-planner', action='append', default=[], metavar='FILE.py:CLASS')
    parser.add_argument('--simulation-seeds', nargs='+', type=int)
    parser.add_argument('--inflation-radius', type=float, default=0.0)
    parser.add_argument('--baseline', help='analysis baseline; defaults to astar if selected, otherwise the first baseline')
    parser.add_argument('--report-seed', type=int, help='recorded seed to display; defaults to the first simulation seed')
    parser.add_argument('--spacing', type=float, default=0.1, help='analysis path sampling spacing in metres')
    for field in fields(NoiseConfig):
        parser.add_argument('--' + field.name.replace('_', '-'), type=float, default=0.0)
    return parser


def _preflight(parser, args):
    output = args.output_dir.resolve()
    if args.output_dir.is_symlink() or output.exists():
        parser.error('output directory already exists; choose a new --output-dir')
    if len(set(args.planners)) != len(args.planners):
        parser.error('planner names must be unique')
    if not isfinite(args.inflation_radius) or args.inflation_radius < 0:
        parser.error('inflation radius must be finite and non-negative')
    if not isfinite(args.spacing) or args.spacing <= 0:
        parser.error('spacing must be finite and positive')
    try:
        scenario = load_scenario(args.scenario)
        load_occupancy_map(scenario.map_path)
        NoiseConfig(**{field.name: getattr(args, field.name) for field in fields(NoiseConfig)})
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.error(str(exc))
    seeds = args.simulation_seeds if args.simulation_seeds is not None else [scenario.simulation_seed]
    if any(seed < 0 for seed in seeds) or len(set(seeds)) != len(seeds):
        parser.error('simulation seeds must be unique non-negative integers')
    if args.report_seed is not None and args.report_seed not in seeds:
        parser.error('report seed must be one of the simulation seeds')
    baseline = args.baseline if args.baseline is not None else ('astar' if 'astar' in args.planners else args.planners[0])
    if baseline not in args.planners and not args.custom_planner:
        parser.error('analysis baseline must be a selected planner')
    # Custom names are known only after loading. Do not execute a plugin twice to
    # discover them: validate an explicitly requested custom baseline from manifest.
    return output, seeds, baseline


def _experiment_arguments(args, output, seeds):
    command = [str(args.scenario.resolve()), '--output', str(output / 'comparison.csv'),
               '--planners', *args.planners, '--simulation-seeds', *map(str, seeds),
               '--inflation-radius', str(args.inflation_radius)]
    for spec in args.custom_planner:
        command += ['--custom-planner=' + spec]
    for field in fields(NoiseConfig):
        command += ['--' + field.name.replace('_', '-'), str(getattr(args, field.name))]
    return command


def _timestamp():
    return datetime.now(timezone.utc).isoformat()


def _save_state(path, state):
    # Replacing only our status file keeps the last complete JSON on interruption.
    temporary = None
    try:
        with NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                prefix='.workflow-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    output, seeds, baseline = _preflight(parser, args)
    summary = output / 'comparison.csv'
    report_arguments = [str(summary), '--output', str(output / 'comparison.png')]
    if args.report_seed is not None:
        report_arguments += ['--seed', str(args.report_seed)]
    phases = (
        ('experiment', experiment.main, _experiment_arguments(args, output, seeds)),
        ('analysis', analyze.main, [str(summary), '--output-dir', str(output / 'analysis'),
                                  '--baseline=' + baseline, '--spacing', str(args.spacing)]),
        ('report', custom_report.main, report_arguments),
    )
    state = {
        'schema_version': 1, 'status': 'running', 'created_at_utc': _timestamp(),
        'current_phase': None, 'failed_phase': None,
        'baseline': baseline, 'simulation_seeds': seeds,
        'report_seed': seeds[0] if args.report_seed is None else args.report_seed,
        'phases': {name: {'status': 'pending', 'arguments': command} for name, _, command in phases},
        'artifacts': {'summary': 'comparison.csv', 'paths': 'comparison_paths.csv',
                      'trajectory': 'comparison_trajectory.csv', 'manifest': 'comparison_manifest.json',
                      'analysis': 'analysis', 'report': 'comparison.png'},
    }
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        parser.error(str(exc))
    status_path = output / 'workflow.json'
    _save_state(status_path, state)
    for name, run, command in phases:
        phase = state['phases'][name]
        state['current_phase'] = name
        phase.update(status='running', started_at_utc=_timestamp())
        _save_state(status_path, state)
        started = perf_counter()
        try:
            if name == 'analysis':
                manifest = json.loads((output / 'comparison_manifest.json').read_text(encoding='utf-8'))
                if baseline not in manifest['planners']:
                    raise ValueError(f'analysis baseline {baseline!r} is absent from the completed comparison')
            code = run(command)
            if code not in (None, 0):
                raise SystemExit(code)
        except (Exception, SystemExit, KeyboardInterrupt) as exc:
            code = 130 if isinstance(exc, KeyboardInterrupt) else (
                exc.code if isinstance(exc, SystemExit) and isinstance(exc.code, int) and exc.code != 0 else 1)
            phase.update(status='failed', finished_at_utc=_timestamp(), duration_s=perf_counter() - started)
            state.update(status='failed', failed_phase=name, finished_at_utc=_timestamp(),
                         error={'type': type(exc).__name__, 'message': str(exc), 'exit_code': code,
                                'control_exception': isinstance(exc, (KeyboardInterrupt, SystemExit))})
            _save_state(status_path, state)
            print(f'workflow failed during {name}; partial outputs preserved in {output}: {exc}', file=sys.stderr)
            return code
        phase.update(status='complete', finished_at_utc=_timestamp(), duration_s=perf_counter() - started)
        _save_state(status_path, state)
    state.update(status='complete', current_phase=None, finished_at_utc=_timestamp())
    _save_state(status_path, state)
    print(f'workflow={status_path}\nreport={output / "comparison.png"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
