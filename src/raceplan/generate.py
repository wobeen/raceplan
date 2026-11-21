"""Generate seeded map/scenario families, or verify one (raceplan-generate).

    raceplan-generate create gate --seeds 11:18 --output-dir generated/gates
    raceplan-generate create staggered_windows --seeds 0:9 --param offset=6 --output-dir generated/windows
    raceplan-generate verify generated/gates
    raceplan-suite generated/gates/suite.yaml --output-dir results/raw/gates

The same kind, parameters and seed always give the same files (see raceplan.seed_maps). A seed whose map has no
drivable path for the default vehicle is recorded as rejected, never redrawn; suite.yaml is only written when every
seed passed. Exit codes: 0 all seeds passed (or verified), 3 written with rejected seeds, 2 bad arguments,
1 I/O error or a verification mismatch.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from raceplan import seed_maps


def _seeds(text):
    first, separator, last = text.partition(':')
    try:
        values = (int(first), int(last if separator else first))
    except ValueError:
        raise argparse.ArgumentTypeError('seeds must be FIRST:LAST (or one seed), integers') from None
    return values


def _param(text):
    key, separator, value = text.partition('=')
    try:
        if not separator or not key.strip():
            raise ValueError(text)
        return key.strip(), int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('a parameter is KEY=INTEGER') from None


def _parser():
    parser = argparse.ArgumentParser(prog='raceplan-generate', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('create', help='generate a new family folder', allow_abbrev=False)
    create.add_argument('kind', choices=tuple(seed_maps.PARAMS))
    create.add_argument('--seeds', type=_seeds, required=True, metavar='FIRST:LAST')
    create.add_argument('--param', type=_param, action='append', default=[], metavar='KEY=INT',
                        help='; '.join(f'{kind}: ' + ', '.join(f'{name}={default} [{low}..{high}]'
                                                               for name, (default, low, high) in params.items())
                                       for kind, params in seed_maps.PARAMS.items()))
    create.add_argument('--revision', type=int, default=seed_maps.REVISION)
    create.add_argument('--output-dir', type=Path, required=True, help='a new folder (refused if it exists)')
    verify = commands.add_parser('verify', help='regenerate a family and compare it byte for byte', allow_abbrev=False)
    verify.add_argument('folder', type=Path)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == 'verify':
        problems = seed_maps.verify_family(args.folder)
        for problem in problems:
            print(problem, file=sys.stderr)
        print('verified' if not problems else f'{len(problems)} problem(s)')
        return 0 if not problems else 1
    keys = [key for key, _ in args.param]
    if len(set(keys)) != len(keys):
        parser.error('a parameter is given twice')
    try:
        spec = seed_maps.normalize(args.kind, dict(args.param), args.revision)
        record = seed_maps.write_family(spec, args.seeds[0], args.seeds[1], args.output_dir)
    except seed_maps.SpecError as exc:
        parser.error(str(exc))
    except FileExistsError:
        parser.error(f'{args.output_dir} already exists; choose a new --output-dir')
    except OSError as exc:
        print(f'raceplan-generate: {exc}', file=sys.stderr)
        return 1
    rejected = [member for member in record['members'] if member['status'] == 'rejected']
    for member in rejected:
        print(f'seed {member["seed"]}: rejected ({member["reason"]})')
    print(f'family={args.output_dir}\nmembers={len(record["members"]) - len(rejected)} ok, {len(rejected)} rejected')
    print(f'suite={args.output_dir / "suite.yaml"}' if record['suite'] else 'suite=not written (a seed was rejected)')
    return 3 if rejected else 0


if __name__ == '__main__':
    raise SystemExit(main())
