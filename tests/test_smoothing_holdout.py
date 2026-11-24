"""Seal, novelty, and decision-rule checks; no planner runs on the held-out maps."""
import importlib.util
import json
from pathlib import Path

import pytest

from raceplan.common import footprint_in_collision
from raceplan.defaults import baseline_vehicle

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('smoothing_holdout', ROOT / 'results/smoothing_holdout.py')
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


def test_new_maps_and_queries_differ_from_all_stored_history():
    history = suite.historical_inventory(ROOT / 'results/raw/smoothing_holdout_20261123')
    # The shared copy of this split is committed after the run; it is not prior history.
    own_copy = ('results', 'analysis', 'smoothing_holdout_20261123')
    old_maps = {value for key, value in history['map_fingerprints_v2'].items()
                if Path(key).parts[:3] != own_copy}
    old_queries = {value for key, value in history['query_fingerprints_v2'].items()
                   if Path(key).parts[:3] != own_copy}
    # The previous sealed split must be part of the inventory.
    scenario = suite.load_scenario(
        ROOT / 'results/analysis/turn_aware_holdout_20261103/inputs/evaluation/offset_islands/q0.yaml')
    grid = suite.load_occupancy_map(scenario.map_path).grid
    assert suite.identity.grid_fingerprint_v2(grid) in old_maps
    assert suite.identity.query_fingerprint_v2(grid, scenario.start, scenario.goal) in old_queries
    maps, queries = set(), set()
    for family in suite.FAMILIES:
        for variant in suite.VARIANTS:
            grid, pairs, _ = suite.design(family, variant)
            fingerprint = suite.identity.grid_fingerprint_v2(grid)
            assert fingerprint not in maps | old_maps
            maps.add(fingerprint)
            for start, goal in pairs:
                query = suite.identity.query_fingerprint_v2(grid, start, goal)
                assert query not in queries | old_queries
                queries.add(query)
                assert not footprint_in_collision(grid, start, baseline_vehicle())
                assert not footprint_in_collision(grid, goal, baseline_vehicle())
    assert len(maps) == 6 and len(queries) == 12
    assert set(suite.SEEDS).isdisjoint({11, 12, 13, 21, 22, 23})


def prepare(tmp_path, monkeypatch):
    monkeypatch.setattr(suite, 'historical_inventory', lambda _: {
        'map_fingerprints_v2': {}, 'query_fingerprints_v2': {}})
    target = tmp_path / 'sealed'
    suite.prepare(target)
    return target


def test_seal_covers_inputs_sources_and_design_and_rejects_changes(tmp_path, monkeypatch):
    folder = prepare(tmp_path, monkeypatch)
    protocol = suite.verify_seal(folder)
    assert protocol['episodes'] == 180 and len(protocol['members']) == 12
    assert protocol['candidate_config']['target_clearance_m'] == .30
    assert 'examples/smoothed_astar_planner.py' in protocol['source_sha256']
    assert 'results/turn_aware_query_identity_v2.py' in protocol['source_sha256']
    scenario = folder / protocol['members'][0]['scenario']
    original = scenario.read_text(encoding='utf-8')
    scenario.write_text(original + '\n# changed\n', encoding='utf-8')
    with pytest.raises(ValueError, match='input seal mismatch'):
        suite.verify_seal(folder)
    scenario.write_text(original, encoding='utf-8')
    snapshot = folder / 'design_snapshot.md'
    snapshot.write_text(snapshot.read_text(encoding='utf-8') + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='design snapshot seal mismatch'):
        suite.verify_seal(folder)


def test_changed_candidate_configuration_is_refused_before_creating_files(tmp_path, monkeypatch):
    monkeypatch.setitem(suite.FIXED_CONFIG, 'smoothing_weight', 50.)
    with pytest.raises(ValueError, match='differs from the fixed protocol'):
        suite.prepare(tmp_path / 'sealed')
    assert not (tmp_path / 'sealed').exists()


def test_claimed_run_refuses_reexecution_before_any_planning(tmp_path, monkeypatch):
    folder = prepare(tmp_path, monkeypatch)
    suite.write_json(folder / 'execution_started.json', {'attempt': 1})
    monkeypatch.setattr(suite, 'experiment', lambda _: pytest.fail('a claimed run must not replan'))
    with pytest.raises(FileExistsError):
        suite.execute(folder)
    with pytest.raises(ValueError, match='already exists'):
        suite.prepare(folder)


def synthetic(candidate_outcomes):
    """Episodes/pairs where A* fails everywhere except where marked; candidate per mapping."""
    episodes, paired = [], []
    for family_index, family in enumerate(suite.FAMILIES):
        case = f'{family}_a_q0'
        for seed in suite.SEEDS:
            astar, candidate = candidate_outcomes[family][suite.SEEDS.index(seed)]
            for planner in suite.PLANNERS:
                reached = candidate if planner == suite.CANDIDATE_NAME else astar
                episodes.append({
                    'case': case, 'family': family, 'simulation_seed': str(seed), 'planner': planner,
                    'failure_class': 'reached' if reached else 'driving_collision',
                    'collision': str(not reached), 'simulation_status': 'reached' if reached else 'collision',
                    'planning_status': 'success', 'tracking_rmse_m': '0.05', 'completion_time_s': '12',
                    'driving_min_sampled_clearance_m': '0.1'})
                if planner != 'astar':
                    paired.append({
                        'family': family, 'planner': planner,
                        'planner_outcome': 'reached' if reached else 'collision',
                        'baseline_outcome': 'reached' if astar else 'collision',
                        'both_reached': str(reached and astar), 'delta_tracking_rmse_m': '',
                        'delta_completion_time_s': '', 'delta_driving_min_sampled_clearance_m': '0'})
    plans = [{'planner': planner, 'planning_time_ms': '1'} for planner in suite.PLANNERS]
    return episodes, plans, paired


def test_decision_requires_overall_gain_without_any_family_net_loss(tmp_path):
    gain = [(False, True)] * 3
    loss = [(True, False), (False, False), (False, False)]
    episodes, plans, paired = synthetic({'staggered_windows': gain, 'offset_islands': gain,
                                         'slalom_walls': loss})
    (tmp_path / 'mixed').mkdir()
    mixed = suite.aggregate(tmp_path / 'mixed', episodes, plans, paired, [])['decision']
    assert (mixed['overall_wins'], mixed['overall_losses']) == (6, 1)
    assert mixed['family_net']['slalom_walls'] == -1 and not mixed['held_out_supported']

    episodes, plans, paired = synthetic({'staggered_windows': gain, 'offset_islands': gain,
                                         'slalom_walls': [(False, False)] * 3})
    (tmp_path / 'clean').mkdir()
    result = suite.aggregate(tmp_path / 'clean', episodes, plans, paired, [])
    assert result['decision']['held_out_supported']
    assert result['versus_hybrid'] == {'pairs': 9, 'candidate_only': 6, 'hybrid_only': 0, 'both': 0}
    candidate = next(r for r in result['outcomes'] if r['planner'] == suite.CANDIDATE_NAME)
    assert (candidate['episodes'], candidate['reached'], candidate['collisions']) == (9, 6, 3)
    worst = (tmp_path / 'clean' / 'worst.csv').read_text(encoding='utf-8')
    assert worst.count('failure,') == 3 + 4 * 9
    assert json.loads(json.dumps(result['decision']))['rule']
