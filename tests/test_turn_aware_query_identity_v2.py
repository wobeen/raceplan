import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image
import pytest
import yaml

from raceplan.common import OccupancyGrid, Pose2D

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('turn_query_v2', ROOT / 'results/turn_aware_query_identity_v2.py')
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


def test_numeric_identity_normalizes_int_float_and_signed_zero_without_rounding():
    first = OccupancyGrid(np.zeros((3, 3), dtype=bool), 1, 0, 0)
    second = OccupancyGrid(first.occupied, 1.0, -0.0, 0.0)
    assert identity.grid_fingerprint_v2(first) == identity.grid_fingerprint_v2(second)
    a = identity.query_fingerprint_v2(first, Pose2D(1, 1, 0), Pose2D(2, 2, -0.0))
    b = identity.query_fingerprint_v2(second, Pose2D(1.0, 1.0, 0.0), Pose2D(2.0, 2.0, 0))
    assert a == b
    assert a != identity.query_fingerprint_v2(second, Pose2D(1.0, 1.0, 1e-15), Pose2D(2.0, 2.0, 0))
    assert identity.canonical_number(2**53 + 1) != identity.canonical_number(float(2**53 + 1))


def test_saved_scenario_roundtrip_matches_and_changed_coordinate_is_rejected(tmp_path):
    occupied = np.zeros((3, 3), dtype=bool)
    Image.fromarray(np.full((3, 3), 255, dtype='uint8')).save(tmp_path / 'map.pgm')
    (tmp_path / 'map.yaml').write_text(yaml.safe_dump({
        'image': 'map.pgm', 'resolution': 1, 'origin': [0, 0, 0],
        'source': 'identity regression', 'license': 'CC0-1.0'}), encoding='utf-8')
    scenario = {'name': 'roundtrip', 'map': 'map.yaml', 'start': [0.5, 0.5, 0],
                'goal': [2.5, 2.5, 0], 'map_seed': None, 'simulation_seed': 0, 'timeout_s': 1}
    path = tmp_path / 'query.yaml'
    path.write_text(yaml.safe_dump(scenario), encoding='utf-8')
    grid, start, goal = OccupancyGrid(occupied, 1), Pose2D(.5, .5, 0), Pose2D(2.5, 2.5, 0)
    assert identity.validate_scenario_roundtrip(grid, start, goal, path) == identity.query_fingerprint_v2(grid, start, goal)
    scenario['start'][2] = .01
    path.write_text(yaml.safe_dump(scenario), encoding='utf-8')
    with pytest.raises(ValueError, match='coordinates differ'):
        identity.validate_scenario_roundtrip(grid, start, goal, path)


def test_roundtrip_rejects_changed_map(tmp_path):
    Image.fromarray(np.array([[255, 0], [255, 255]], dtype='uint8')).save(tmp_path / 'map.pgm')
    (tmp_path / 'map.yaml').write_text(yaml.safe_dump({
        'image': 'map.pgm', 'resolution': 1, 'origin': [0, 0, 0],
        'source': 'identity regression', 'license': 'CC0-1.0'}), encoding='utf-8')
    (tmp_path / 'query.yaml').write_text(yaml.safe_dump({
        'name': 'roundtrip', 'map': 'map.yaml', 'start': [.5, .5, 0], 'goal': [1.5, 1.5, 0],
        'map_seed': None, 'simulation_seed': 0, 'timeout_s': 1}), encoding='utf-8')
    with pytest.raises(ValueError, match='map differs'):
        identity.validate_scenario_roundtrip(OccupancyGrid(np.zeros((2, 2), dtype=bool), 1),
                                             Pose2D(.5, .5), Pose2D(1.5, 1.5), tmp_path / 'query.yaml')
