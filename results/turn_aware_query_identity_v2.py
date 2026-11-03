"""Canonical numeric query identities and a read-only v1-run correction audit.

No planner or simulator is called. The v1 runner and all sealed artifacts stay intact.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from math import isfinite
from numbers import Integral, Real
from pathlib import Path

from raceplan.common import Pose2D, load_occupancy_map, load_scenario

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def canonical_number(value):
    """Unify integer/float and signed zero, without rounding coordinates."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError('identity coordinates must be real numbers')
    if isinstance(value, Integral):
        return int(value)
    number = float(value)
    if not isfinite(number):
        raise ValueError('identity coordinates must be finite')
    return int(number) if number.is_integer() else number


def canonical_pose(pose):
    return {key: canonical_number(getattr(pose, key)) for key in ('x', 'y', 'yaw')}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def grid_fingerprint_v2(grid):
    header = {'schema': 'raceplan-grid-v2', 'width': grid.width, 'height': grid.height,
              'resolution': canonical_number(grid.resolution),
              'origin_x': canonical_number(grid.origin_x), 'origin_y': canonical_number(grid.origin_y)}
    return sha256(canonical_json(header) + b'\n' + grid.occupied.tobytes()).hexdigest()


def query_fingerprint_v2(grid, start, goal):
    query = {'schema': 'raceplan-query-v2', 'grid_sha256': grid_fingerprint_v2(grid),
             'start': canonical_pose(start), 'goal': canonical_pose(goal)}
    return sha256(canonical_json(query)).hexdigest()


def validate_scenario_roundtrip(grid, start, goal, scenario_path):
    """For future seals: validate serialized inputs before sealing or planning."""
    scenario = load_scenario(scenario_path)
    loaded_grid = load_occupancy_map(scenario.map_path).grid
    if grid_fingerprint_v2(grid) != grid_fingerprint_v2(loaded_grid):
        raise ValueError('scenario round-trip map differs from the design')
    if (canonical_pose(start), canonical_pose(goal)) != (canonical_pose(scenario.start), canonical_pose(scenario.goal)):
        raise ValueError('scenario round-trip coordinates differ from the design')
    expected = query_fingerprint_v2(grid, start, goal)
    actual = query_fingerprint_v2(loaded_grid, scenario.start, scenario.goal)
    if expected != actual:
        raise ValueError('scenario round-trip identity differs from the design')
    return actual


def load_v1():
    spec = importlib.util.spec_from_file_location('_turn_aware_holdout_preserved_v1', ROOT / 'results/turn_aware_holdout.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def audit_v1_run(run_dir):
    """Verify all original seals and artifacts, then derive corrected identities."""
    run_dir = run_dir.resolve()
    v1 = load_v1()
    protocol = v1.verify_seal(run_dir)
    if protocol.get('version') != 1:
        raise ValueError('this correction applies only to the preserved v1 protocol')
    complete_path = run_dir / 'complete.json'
    complete_hash = digest(complete_path)
    complete = json.loads(complete_path.read_text(encoding='utf-8'))
    if complete.get('status') != 'complete' or complete['seal_sha256'] != digest(run_dir / 'seal.json'):
        raise ValueError('original completion/seal mismatch')
    for name, expected in complete['artifact_sha256'].items():
        path = (run_dir / name).resolve()
        if not path.is_relative_to(run_dir) or digest(path) != expected:
            raise ValueError(f'original artifact mismatch: {name}')
    records = []
    for member in protocol['members']:
        grid, queries, _ = v1.design(member['split'], member['family'])
        start, goal = queries[member['query']]
        scenario_path = run_dir / member['scenario']
        scenario = load_scenario(scenario_path)
        loaded = load_occupancy_map(scenario.map_path).grid
        original_design_hash = v1.query_fingerprint(grid, start, goal)
        original_roundtrip_hash = v1.query_fingerprint(loaded, scenario.start, scenario.goal)
        if original_design_hash != member['query_fingerprint']:
            raise ValueError('original design query does not reproduce the stored v1 identity')
        if not (v1.grid_fingerprint(grid) == v1.grid_fingerprint(loaded) == member['map_fingerprint']):
            raise ValueError('original map identity does not match design and serialized map')
        corrected = validate_scenario_roundtrip(grid, start, goal, scenario_path)
        batch = f'{member["split"]}_{member["family"]}_q{member["query"]}'
        manifest = json.loads((run_dir / 'batches' / batch / 'comparison_manifest.json').read_text(encoding='utf-8'))
        actual_start, actual_goal = (Pose2D(**manifest['scenario'][key]) for key in ('start', 'goal'))
        manifest_matches = (
            canonical_pose(actual_start) == canonical_pose(scenario.start)
            and canonical_pose(actual_goal) == canonical_pose(scenario.goal)
            and manifest['scenario_sha256'] == digest(scenario_path)
            and Path(manifest['scenario_file']).resolve() == scenario_path.resolve()
            and Path(manifest['scenario']['map_path']).resolve() == scenario.map_path.resolve()
        )
        if not manifest_matches:
            raise ValueError('execution manifest does not match the unchanged serialized query')
        records.append({
            'split': member['split'], 'family': member['family'], 'query': member['query'],
            'scenario': member['scenario'], 'scenario_sha256': digest(scenario_path),
            'old_stored_query_fingerprint': member['query_fingerprint'],
            'old_design_query_fingerprint': original_design_hash,
            'old_roundtrip_query_fingerprint': original_roundtrip_hash,
            'old_roundtrip_matches_stored': original_roundtrip_hash == member['query_fingerprint'],
            'canonical_design_query_fingerprint_v2': query_fingerprint_v2(grid, start, goal),
            'canonical_roundtrip_query_fingerprint_v2': corrected,
            'canonical_identity_matches': corrected == query_fingerprint_v2(grid, start, goal),
            'design_start': asdict(start), 'design_goal': asdict(goal),
            'loaded_start': asdict(scenario.start), 'loaded_goal': asdict(scenario.goal),
            'coordinates_equal_without_tolerance': True, 'map_identity_matches_v1': True,
            'execution_manifest_matches_query': True,
        })
    # Recheck original inputs/sources and completion marker after the read-only audit.
    v1.verify_seal(run_dir)
    if digest(complete_path) != complete_hash:
        raise ValueError('original completion changed during correction audit')
    return {
        'correction_schema_version': 2, 'original_run': str(run_dir),
        'correction_is_posthoc': True, 'original_query_hashes_replaced': False,
        'original_protocol_sha256': digest(run_dir / 'protocol.json'),
        'original_seal_sha256': digest(run_dir / 'seal.json'),
        'original_complete_sha256': complete_hash,
        'audit_tool_sha256': digest(Path(__file__).resolve()),
        'original_sources_verified': len(protocol['source_sha256']),
        'original_inputs_verified': len(protocol['input_sha256']),
        'original_artifacts_verified': len(complete['artifact_sha256']),
        'members': records, 'members_verified': len(records),
        'old_numeric_serialization_mismatches': sum(not r['old_roundtrip_matches_stored'] for r in records),
        'canonical_roundtrip_mismatches': sum(not r['canonical_identity_matches'] for r in records),
        'conclusion': 'v1 identity serialization defect only; sealed input bytes, maps, coordinates and outcomes unchanged',
        'impact': 'v1 stored semantic query fingerprints cannot be matched directly to loaded scenarios; use this versioned correction',
        'future_preseal_rule': 'use query_fingerprint_v2 and validate_scenario_roundtrip before any planning or sealing',
        'original_files_modified': False, 'planner_calls': 0, 'simulation_calls': 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    run_dir, output = args.run_dir.resolve(), args.output_dir.resolve()
    if output.exists() or output.is_relative_to(run_dir):
        parser.error('select a new correction directory outside the preserved original run')
    correction = audit_v1_run(run_dir)
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'correction.json').open('x', encoding='utf-8') as stream:
        json.dump(correction, stream, indent=2, ensure_ascii=False, allow_nan=False)
    with (output / 'correction_sha256.json').open('x', encoding='utf-8') as stream:
        json.dump({'correction.json': digest(output / 'correction.json'),
                   str(Path(__file__).resolve()): digest(Path(__file__).resolve())}, stream, indent=2)
    print(f'v1 read-only correction: {correction["members_verified"]} queries; '
          f'{correction["old_numeric_serialization_mismatches"]} old mismatches; '
          f'{correction["canonical_roundtrip_mismatches"]} canonical mismatches; '
          'planner/simulation calls=0')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
