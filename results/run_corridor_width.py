"""Execute the fixed validation gate-width protocol, preserving all failures."""
import argparse
import csv
import json
import hashlib
from pathlib import Path
from raceplan.experiment import main as run
from raceplan.analyze import main as analyze

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', default='corridor_width_20261013')
    args = parser.parse_args()
    if Path(args.name).name != args.name or args.name in {'.', '..'}:
        parser.error('name must be a single directory name')
    raw = ROOT/'results/raw'/args.name
    analysis = ROOT/'results/analysis'/args.name
    if raw.exists() or analysis.exists():
        parser.error('run directories exist; select a new name')
    raw.mkdir(parents=True)
    analysis.mkdir(parents=True)
    family_root = ROOT/'scenarios/corridor_width'
    family = json.loads((family_root/'family.json').read_text())
    noise = ['--initial-position-std-m', '0.02', '--initial-yaw-std-rad', '0.01',
             '--initial-speed-std-mps', '0.01', '--steering-std-rad', '0.01',
             '--speed-measurement-std-mps', '0.02']
    protocol = dict(family=family, conditions=['zero', 'noise'], seeds=[0, 1, 2],
                    noise_arguments=noise, inflation_radius_m=0.0, status='running',
                    note='Validation pilot, unchanged baseline defaults. Point-grid vs footprint planning distinction retained.')
    protocol['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (analysis/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')
    collected = []
    for member in family['members']:
        scenario = family_root/member['scenario']
        for condition in protocol['conditions']:
            name = scenario.stem+'_'+condition
            output = raw/f'{name}.csv'
            run([str(scenario), '--output', str(output), '--simulation-seeds', '0', '1', '2']
                + (noise if condition == 'noise' else []))
            analyze([str(output), '--output-dir', str(analysis/name)])
            with (analysis/name/'episodes.csv').open(newline='') as stream:
                for row in csv.DictReader(stream):
                    collected.append(dict(batch=name, width_m=member['width_m'],
                                          condition=condition, **row))
            print(f'finished {name}', flush=True)
        if ((raw/(scenario.stem+'_zero_paths.csv')).read_bytes()
                != (raw/(scenario.stem+'_noise_paths.csv')).read_bytes()):
            raise ValueError('planned paths changed between noise conditions')
    with (analysis/'width_comparison.csv').open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(collected[0]))
        writer.writeheader(); writer.writerows(collected)
    protocol['status'] = 'complete'
    (analysis/'protocol.json').write_text(json.dumps(protocol, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
