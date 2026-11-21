from hashlib import sha256
import json
import os
from pathlib import Path

import numpy as np
import pytest

from raceplan import generate, seed_maps
from raceplan.common import load_scenario
from raceplan.common.map_io import load_occupancy_map
from raceplan.common.vehicle import footprint_in_collision
from raceplan.defaults import baseline_vehicle

# Seed 7 with default parameters, revision 1. These change only with a new generator revision; a different value on
# another OS, Python or NumPy means the same seed no longer gives the same map there.
GOLDEN = {'offset_islands': '550f9d1eaced53069fe0d557030db5bc8e408d5ca1783239094c9257e048e503',
          'staggered_windows': '35f4d807bc2161f1488ff0e24f9ace4cf42590cf25d95317b8e3662fccf853b2',
          'gate': '28749e52124a0c942d4062f3f30c7870da7d1c0920d17aad7f700750e7da5217'}


def _digest(member):
    return sha256(b''.join(member.files[name] for name in sorted(member.files))).hexdigest()


@pytest.mark.parametrize('kind', sorted(seed_maps.PARAMS))
def test_a_seed_always_gives_the_same_bytes_everywhere(kind):
    spec = seed_maps.normalize(kind)
    member = seed_maps.build_member(spec, 7)
    assert member.reason is None and _digest(member) == GOLDEN[kind]
    assert _digest(seed_maps.build_member(seed_maps.normalize(kind), 7)) == GOLDEN[kind]
    maps = {seed_maps.build_member(spec, seed).files['map.pgm'] for seed in range(10)}
    assert len(maps) > 1  # The seed changes the map itself, not only the metadata that names it.


@pytest.mark.parametrize('kind', sorted(seed_maps.PARAMS))
def test_generated_files_load_as_ordinary_maps_and_scenarios(kind, tmp_path):
    spec = seed_maps.normalize(kind)
    seed_maps.write_family(spec, 3, 4, tmp_path / 'family')
    record = json.loads((tmp_path / 'family/family.json').read_text(encoding='ascii'))
    for member in record['members']:
        assert member['status'] == 'ok'
        scenario = load_scenario(tmp_path / 'family/members' / member['name'] / 'q0.yaml')
        grid = load_occupancy_map(scenario.map_path).grid
        geometry = json.loads((tmp_path / 'family/members' / member['name'] / 'geometry.json').read_text())
        assert scenario.map_seed == member['seed'] and scenario.name == member['name']
        assert grid.occupied.shape == (spec.params['height'], spec.params['width'])
        c0, r0, c1, r1 = geometry['obstacles_cells'][0]
        assert grid.occupied[r0, c0] and grid.occupied[r1 - 1, c1 - 1]  # Row 0 is the bottom, as the loader reads it.
        for pose in (scenario.start, scenario.goal):
            assert not footprint_in_collision(grid, pose, baseline_vehicle())


def test_parameters_are_checked_before_any_seed_is_used():
    for kind, params in (('nope', {}), ('gate', {'width': True}), ('gate', {'colour': 1}), ('gate', {'width': 63}),
                         ('gate', {'gap_min': 4}), ('gate', {'gap_min': 9, 'gap_max': 5}),
                         ('staggered_windows', {'jitter': 4, 'offset': 4}),
                         ('staggered_windows', {'height': 40, 'window_h': 28, 'offset': 18, 'jitter': 4}),
                         ('offset_islands', {'width': 64, 'islands': 4, 'block_w': 10})):
        with pytest.raises(seed_maps.SpecError):
            seed_maps.normalize(kind, params)
    with pytest.raises(seed_maps.SpecError):
        seed_maps.normalize('gate', revision=2)
    spec = seed_maps.normalize('gate')
    for seeds in ((5, 1), (-1, 3), (0, 2**31), (0, seed_maps.MAX_SEEDS)):
        with pytest.raises(seed_maps.SpecError):
            seed_maps.build_family(spec, *seeds)


def test_a_seed_without_a_drivable_path_is_rejected_not_redrawn():
    narrow = seed_maps.normalize('gate', {'gap_min': 3, 'gap_max': 3})  # 0.3 m is narrower than the 0.31 m vehicle
    assert seed_maps.build_member(narrow, 1).reason == 'gate_clearance'
    assert seed_maps.build_member(seed_maps.normalize('gate', {'gap_min': 5, 'gap_max': 5}), 1).reason is None
    walled = np.zeros((60, 80), dtype=bool)
    walled[0, :] = walled[-1, :] = walled[:, 0] = walled[:, -1] = True
    walled[1:41, 38:42] = True  # A wall with an opening at rows 41-58, far above the start and goal row 10.
    found, _ = seed_maps._lattice_witness(seed_maps._Free(walled), (7, 10), (72, 10))
    assert found  # Turn up, pass the opening, turn down and arrive facing +x.
    walled[41:49, 38:42] = True  # 10 free rows: too few for the padded arc that lines up with the opening.
    assert not seed_maps._lattice_witness(seed_maps._Free(walled), (7, 10), (72, 10))[0]
    # The goal must be reached facing +x as written in q0.yaml; reaching the cell from the side does not count.
    side = seed_maps.normalize('staggered_windows', {'width': 73, 'height': 94, 'wall_w': 7, 'window_h': 22,
                                                     'offset': 11, 'jitter': 4})
    assert seed_maps.build_member(side, 5).reason == 'no_motion_witness'


def test_a_family_is_written_once_and_verifies_byte_for_byte(tmp_path, monkeypatch):
    spec = seed_maps.normalize('staggered_windows')
    out = tmp_path / 'windows'
    record = seed_maps.write_family(spec, 0, 2, out)
    assert record['suite'] is not None and (out / 'suite.yaml').is_file()
    assert seed_maps.verify_family(out) == []
    with pytest.raises(FileExistsError):
        seed_maps.write_family(spec, 0, 2, out)
    member = out / 'members' / record['members'][1]['name']
    original = (member / 'map.yaml').read_bytes()
    (member / 'map.yaml').write_bytes(original + b'#')
    (out / 'stray.txt').write_text('x')
    problems = seed_maps.verify_family(out)
    assert any('map.yaml' in problem for problem in problems) and any('stray.txt' in problem for problem in problems)
    (member / 'map.yaml').write_bytes(original)
    (out / 'stray.txt').unlink()
    (member / 'q0.yaml').unlink()
    assert any('missing file' in problem for problem in seed_maps.verify_family(out))
    (member / 'q0.yaml').write_bytes(seed_maps.build_member(spec, record['members'][1]['seed']).files['q0.yaml'])
    manifest = (out / 'family.json').read_bytes()
    (out / 'family.json').write_bytes(manifest.replace(b'"schema_version":1', b'"schema_version":true'))
    assert seed_maps.verify_family(out) == ['family.json differs from a fresh generation']  # true == 1 in Python
    (out / 'family.json').write_bytes(manifest)
    real_scandir = os.scandir

    def unreadable(path='.'):
        if Path(path).name == 'members':
            raise PermissionError(13, 'Access is denied', str(path))
        return real_scandir(path)
    monkeypatch.setattr(os, 'scandir', unreadable)
    assert any('cannot list' in problem for problem in seed_maps.verify_family(out))  # Never "verified" unseen.
    monkeypatch.undo()
    assert seed_maps.verify_family(out) == []
    (out / 'family.json').write_bytes(b'[' * 100_000)
    assert seed_maps.verify_family(out)[0].startswith('cannot verify')


def test_rejected_seeds_keep_the_family_but_no_suite(tmp_path, capsys):
    out = tmp_path / 'gates'
    code = generate.main(['create', 'gate', '--seeds', '1:4', '--param', 'gap_min=3', '--param', 'gap_max=7',
                          '--output-dir', str(out)])
    printed = capsys.readouterr().out
    record = json.loads((out / 'family.json').read_text(encoding='ascii'))
    rejected = [member for member in record['members'] if member['status'] == 'rejected']
    assert code == 3 and rejected and 'rejected (gate_clearance)' in printed
    assert record['suite'] is None and not (out / 'suite.yaml').exists()
    assert generate.main(['verify', str(out)]) == 0  # The rejections themselves are part of what verifies.
    for argv in (['create', 'gate', '--seeds', '5:1', '--output-dir', str(tmp_path / 'x')],
                 ['create', 'gate', '--seeds', '1:2', '--param', 'width=80', '--param', 'width=90', '--output-dir', str(tmp_path / 'y')],
                 ['create', 'gate', '--seeds', '1:2', '--output-dir', str(out)]):
        with pytest.raises(SystemExit) as error:
            generate.main(argv)
        assert error.value.code == 2, argv


def test_a_generated_suite_runs_as_it_is(tmp_path):
    from raceplan import suite
    seed_maps.write_family(seed_maps.normalize('gate'), 1, 2, tmp_path / 'gates')
    assert suite.main([str(tmp_path / 'gates/suite.yaml'), '--output-dir', str(tmp_path / 'run')]) == 0
    state = json.loads((tmp_path / 'run/suite.json').read_text(encoding='utf-8'))
    assert state['coverage']['completed_cases'] == 2
