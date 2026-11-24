"""Maximum tracking error behind the margin values in docs/MARGIN_RESCUE_DEVELOPMENT.md.

Reads the local (Git-ignored) raw episodes of the lead-in development run and
summarizes reached ``smoothed_low_clearance`` episodes, overall and split by the
path start offset (the A* path starts at the start cell centre).  Prints JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'results/raw/leadin_rescue_development_20261124/episodes.csv'


def summary(values):
    values = np.asarray(values, dtype=float)
    return {'count': int(len(values)), 'min': float(values.min()),
            'median': float(np.median(values)), 'p90': float(np.percentile(values, 90)),
            'max': float(values.max())}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episodes', type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    with args.episodes.open(newline='', encoding='utf-8') as stream:
        rows = [r for r in csv.DictReader(stream)
                if r['planner'] == 'smoothed_low_clearance' and r['failure_class'] == 'reached']
    groups = {}
    for row in rows:
        groups.setdefault(f"start_offset_{float(row['path_start_offset_m']):.3f}", []).append(
            float(row['max_tracking_error_m']))
    print(json.dumps({'source': str(args.episodes),
                      'all': summary([float(r['max_tracking_error_m']) for r in rows]),
                      **{key: summary(values) for key, values in sorted(groups.items())}},
                     indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
