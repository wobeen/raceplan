"""Run the fixed demo development comparison, without overwriting an earlier run."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from shutil import copyfile

from raceplan.analyze import main as analyze
from raceplan.custom_report import main as report
from raceplan.experiment import main as experiment

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'examples/turn_aware_planner.py'
CONDITIONS = {
    'clean': {},
    'noise': {'initial-position-std-m': 0.02, 'initial-yaw-std-rad': 0.02,
              'steering-std-rad': 0.01, 'speed-measurement-std-mps': 0.02},
}


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def hash_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists():
        parser.error('output directory already exists; choose a new directory')
    output.mkdir(parents=True, exist_ok=False)
    design = output / 'design_snapshot.md'
    copyfile(ROOT / 'docs/TURN_AWARE_CANDIDATE.md', design)
    # Record the fixed protocol before any planner runs. No selection or tuning.
    write_json(output / 'protocol.json', {
        'purpose': 'development comparison on one previously used demo; not held-out evaluation',
        'scenario': str(ROOT / 'scenarios/demo.yaml'),
        'simulation_seeds': [0, 1, 2],
        'planners': ['dijkstra', 'astar', 'hybrid_astar', 'turn_aware_astar', 'turn_aware_zero'],
        'turn_weight_m_per_rad': 0.20,
        'conditions': CONDITIONS,
        'inflation_radius_m': 0.0,
        'success': 'collision-free goal position within 0.5 m; yaw is descriptive',
        'planning_repetitions_per_condition': 1,
        'timing_note': 'planner-reported once, reused across seeds; no timing inference',
        'design_snapshot_sha256': hash_file(design),
        'source_sha256': {str(path.relative_to(ROOT)): hash_file(path)
                          for path in [PLUGIN, Path(__file__)]},
    })
    conditions = {}
    for name, noise in CONDITIONS.items():
        folder = output / name
        summary = folder / 'comparison.csv'
        command = [str(ROOT / 'scenarios/demo.yaml'), '--output', str(summary),
                   '--custom-planner', f'{PLUGIN}:TurnAwareAStar',
                   '--custom-planner', f'{PLUGIN}:LengthOnlyAStar',
                   '--simulation-seeds', '0', '1', '2']
        for setting, value in noise.items():
            command += ['--' + setting, str(value)]
        experiment(command)
        report([str(summary), '--output', str(folder / 'comparison.png')])
        analysis = folder / 'analysis'
        analyze([str(summary), '--baseline', 'astar', '--output-dir', str(analysis)])
        episode_rows = read_csv(analysis / 'episodes.csv')
        planning = {}
        for row in episode_rows:
            if row['planner'] not in planning:
                planning[row['planner']] = {key: row[key] for key in (
                    'planning_status', 'path_cost_m', 'planning_time_ms', 'expanded_nodes',
                    'path_length_m', 'total_absolute_turn_rad', 'max_discrete_curvature_per_m',
                    'min_sampled_footprint_clearance_m',
                )}
        conditions[name] = {
            'outcomes': read_csv(analysis / 'planners.csv'), 'plans': planning,
            'paired_against_astar': read_csv(analysis / 'paired.csv'),
        }
    write_json(output / 'summary.json', conditions)
    write_json(output / 'artifact_sha256.json', {
        str(path.relative_to(output)): hash_file(path)
        for path in sorted(output.rglob('*')) if path.is_file()
    })
    print(f'completed fixed development comparison -> {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
