"""Validate the split and seal without planning on either held-out split."""
import importlib.util
from pathlib import Path

import pytest

from raceplan.common import footprint_in_collision
from raceplan.defaults import baseline_vehicle

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('turn_aware_holdout', ROOT / 'results/turn_aware_holdout.py')
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


def test_new_split_maps_and_queries_differ_from_all_stored_history():
    history = suite.historical_inventory(ROOT / 'results/raw/turn_aware_holdout_20261103')
    assert len(history['query_fingerprints']) == 16
    assert len(set(history['map_fingerprints'].values())) >= 8
    map_hashes, query_hashes = set(), set()
    for split in suite.SPLIT_SEEDS:
        for family in suite.FAMILIES:
            grid, queries, _ = suite.design(split, family)
            fingerprint = suite.grid_fingerprint(grid)
            assert fingerprint not in map_hashes | set(history['map_fingerprints'].values())
            map_hashes.add(fingerprint)
            for start, goal in queries:
                query_hash = suite.query_fingerprint(grid, start, goal)
                assert query_hash not in query_hashes | set(history['query_fingerprints'].values())
                query_hashes.add(query_hash)
                assert not footprint_in_collision(grid, start, baseline_vehicle())
                assert not footprint_in_collision(grid, goal, baseline_vehicle())
    assert len(map_hashes) == 4 and len(query_hashes) == 8
    assert set(suite.SPLIT_SEEDS['validation']).isdisjoint(suite.SPLIT_SEEDS['evaluation'])


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, 'historical_inventory', lambda _: {
        'map_fingerprints': {}, 'query_fingerprints': {}, 'input_sha256': {}})
    target = tmp_path / 'sealed'
    suite.prepare(target)
    return target


def test_seal_covers_sources_queries_design_and_rejects_modified_inputs(tmp_path, monkeypatch):
    folder = prepare(tmp_path, monkeypatch)
    protocol = suite.verify_seal(folder)
    assert protocol['episodes'] == 120
    assert len(protocol['members']) == 8
    assert protocol['turn_weight_m_per_rad'] == .20
    assert protocol['ablation_weight'] == 0
    assert len([m for m in protocol['members'] if m['split'] == 'evaluation']) == 4
    assert any(path.endswith('turn_aware_planner.py') for path in protocol['source_sha256'])
    source = folder / protocol['members'][0]['scenario']
    original = source.read_text(encoding='utf-8')
    source.write_text(original + '\n# changed\n', encoding='utf-8')
    with pytest.raises(ValueError, match='input seal mismatch'):
        suite.verify_seal(folder)
    source.write_text(original, encoding='utf-8')
    suite.verify_seal(folder)
    protocol_file = folder / 'protocol.json'
    protocol_file.write_text(protocol_file.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='protocol seal mismatch'):
        suite.verify_seal(folder)


def test_claimed_run_refuses_reexecution_before_any_planning(tmp_path, monkeypatch):
    folder = prepare(tmp_path, monkeypatch)
    suite.write_json(folder / 'execution_started.json', {'attempt': 1})
    monkeypatch.setattr(suite, 'experiment', lambda _: pytest.fail('a claimed run must not replan'))
    with pytest.raises(FileExistsError):
        suite.execute(folder)
    with pytest.raises(ValueError, match='already exists'):
        suite.prepare(folder)


def test_aggregation_keeps_failures_and_counts_plans_once(tmp_path):
    episodes, plans, pairs = [], [], []
    for planner in suite.PLANNERS:
        for index, status in enumerate(('reached', 'collision', 'timeout', 'not_run')):
            row = {'split': 'evaluation', 'family': suite.FAMILIES[index % 2], 'planner': planner,
                   'planning_status': 'no_path' if status == 'not_run' else 'success',
                   'simulation_status': status, 'collision': str(status == 'collision'),
                   'failure_class': 'planning_no_path' if status == 'not_run' else status,
                   'tracking_rmse_m': '0.2', 'completion_time_s': '10',
                   'driving_min_sampled_clearance_m': '' if status == 'not_run' else '0.1'}
            episodes.append(row)
            plans.append({'planner': planner, 'planning_time_ms': str(index + 1), 'expanded_nodes': '5'})
    result = suite.aggregate(tmp_path, 'evaluation', episodes, plans, pairs)
    assert len(result['outcomes']) == 5
    for row in result['outcomes']:
        assert [row[k] for k in ('episodes', 'reached', 'collisions', 'timeouts', 'planning_failures', 'planning_calls')] == [4, 1, 1, 1, 1, 4]
        assert row['planning_time_ms_median'] == 2.5
    with (tmp_path / 'evaluation_worst.csv').open(encoding='utf-8') as stream:
        assert stream.read().count('failure,') == 15
