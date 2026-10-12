import argparse
import csv
import json
from pathlib import Path
from time import perf_counter
from raceplan.experiment import main

parser = argparse.ArgumentParser(description='Run the two-map repeatability pilot from the repository root.')
parser.add_argument('--output-dir', type=Path, default=Path('results/raw/pilot_20261012'))
root = parser.parse_args().output_dir
root.mkdir(parents=True, exist_ok=True)
noise = ['--initial-position-std-m', '0.02', '--initial-yaw-std-rad', '0.01',
         '--initial-speed-std-mps', '0.01', '--steering-std-rad', '0.01',
         '--speed-measurement-std-mps', '0.02']
report = []
for scenario in ['demo', 'validation_open']:
    for condition in ['zero', 'noise', 'repeat']:
        output = root / f'{scenario}_{condition}.csv'
        started = perf_counter()
        main([f'scenarios/{scenario}.yaml', '--output', str(output),
              '--simulation-seeds', '0', '1', '2'] + ([] if condition == 'zero' else noise))
        elapsed = perf_counter() - started
        with output.open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        for planner in ['dijkstra', 'astar', 'hybrid_astar']:
            episodes = [r for r in rows if r['planner'] == planner]
            report.append(dict(scenario=scenario, condition=condition, planner=planner,
                reached=sum(r['reached'] == 'True' for r in episodes), episodes=len(episodes),
                statuses=[r['simulation_status'] for r in episodes],
                rmse_min=min(float(r['tracking_rmse_m']) for r in episodes),
                rmse_max=max(float(r['tracking_rmse_m']) for r in episodes), batch_seconds=elapsed))
    for suffix in ['_trajectory.csv', '_paths.csv']:
        assert (root / f'{scenario}_noise{suffix}').read_bytes() == (root / f'{scenario}_repeat{suffix}').read_bytes()
    assert (root / f'{scenario}_zero_paths.csv').read_bytes() == (root / f'{scenario}_noise_paths.csv').read_bytes()
(root / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
