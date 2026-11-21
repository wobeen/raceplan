import csv
import http.client
import json
from pathlib import Path
from threading import Thread
from urllib.parse import quote

import pytest
import yaml

from raceplan import experiment, suite, workflow
from raceplan.gui.data import Explorer, UnknownItem, find_runs
from raceplan.gui.analysis import BadQuery
from raceplan.gui.server import make_server
from raceplan.planners import AStarPlanner

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/demo.yaml'


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


@pytest.fixture(scope='module')
def saved(tmp_path_factory):
    root = tmp_path_factory.mktemp('saved')
    custom = f"{ROOT / 'examples/error_planners.py'}:ExceptionPlanner"
    assert workflow.main([str(SCENARIO), '--output-dir', str(root / 'nested/batch'), '--planners', 'astar', 'dijkstra',
                          f'--custom-planner={custom}', '--simulation-seeds', '0', '1',
                          '--steering-std-rad', '0.01']) == 0
    config = {'version': 1, 'planners': ['astar'], 'simulation_seeds': [0], 'cases': [
        {'id': 'demo', 'scenario': str(SCENARIO)},
        {'id': 'open', 'scenario': str(ROOT / 'scenarios/validation_open.yaml')}]}
    config_path = root / 'suite.yaml'
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    assert suite.main([str(config_path), '--output-dir', str(root / 'suite')]) == 0
    return root


@pytest.fixture
def client(saved):
    server = make_server(saved)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def get(path, host=None, method='GET'):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        connection.request(method, path, headers={'Host': host or f'127.0.0.1:{port}'})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    yield get
    server.shutdown()
    server.server_close()


def test_finds_runs_without_treating_their_subfolders_as_runs(saved):
    assert {path.relative_to(saved).as_posix() for path in find_runs(saved)} == {'nested/batch', 'suite'}
    summaries = {item['id']: item for item in Explorer(saved).runs()}
    assert summaries['suite']['kind'] == 'suite' and summaries['suite']['episodes'] == 2
    assert summaries['nested/batch']['outcomes']['planning_error'] == 2


def test_run_and_case_match_saved_files_and_never_plan_or_simulate(saved, monkeypatch):
    monkeypatch.setattr(AStarPlanner, 'plan', lambda *args, **kwargs: pytest.fail('explorer must not plan'))
    monkeypatch.setattr('raceplan.simulator.run_episode', lambda *args, **kwargs: pytest.fail('explorer must not simulate'))
    explorer = Explorer(saved)
    folder = saved / 'nested/batch'
    run = explorer.run('nested/batch')
    case = run['cases'][0]
    assert case['id'] == 'batch' and case['baseline'] == 'astar' and case['seeds'] == [0, 1]
    saved_rows = {row['episode_id']: row for row in read_csv(folder / 'analysis/episodes.csv')}
    assert len(case['episodes']) == len(saved_rows) == 6
    for episode in case['episodes']:
        row = saved_rows[episode['episode_id']]
        assert episode['failure_class'] == row['failure_class']
        expected = float(row['tracking_rmse_m']) if row['tracking_rmse_m'] else None
        assert episode['tracking_rmse_m'] == expected
    failed = next(item for item in case['episodes'] if item['failure_class'] == 'planning_error')
    assert failed['planning_error_message'] == 'intentional custom planning failure'
    saved_pairs = {(row['planner'], row['simulation_seed']): row for row in read_csv(folder / 'analysis/paired.csv')}
    assert len(case['pairs']) == len(saved_pairs)
    for pair in case['pairs']:
        row = saved_pairs[(pair['planner'], str(pair['simulation_seed']))]
        delta = row['delta_tracking_rmse_m']
        assert pair['delta_tracking_rmse_m'] == (float(delta) if delta else None)

    detail = explorer.case('nested/batch', 'batch')
    assert detail['grid']['occupied'] and detail['goal_tolerance'] == 0.5
    samples = [row for row in read_csv(folder / 'comparison_trajectory.csv') if row['episode_id'] == 'astar:0']
    trace = detail['traces']['astar:0']
    assert len(trace['t']) == len(trace['clearance']) == len(samples)
    assert trace['x'][-1] == round(float(samples[-1]['x_m']), 5)
    clearance = [row for row in read_csv(folder / 'analysis/clearance_samples.csv') if row['episode_id'] == 'astar:0']
    assert trace['clearance'][-1] == round(float(clearance[-1]['footprint_clearance_m']), 5)
    assert failed['episode_id'] not in detail['traces'] or not detail['traces'][failed['episode_id']]['t']
    width = detail['grid']['width']
    assert all(0 <= column and column + length <= width for _, column, length in detail['grid']['occupied'])


def test_occupied_runs_rebuild_the_saved_map(saved):
    from raceplan.common import load_occupancy_map
    grid = load_occupancy_map(SCENARIO.parent.parent / 'maps/demo.yaml').grid
    detail = Explorer(saved).case('nested/batch', 'batch')['grid']
    cells = sum(length for _, _, length in detail['occupied'])
    assert cells == int(grid.occupied.sum())
    assert all(grid.occupied[row, column:column + length].all() for row, column, length in detail['occupied'])


def test_reproduce_command_runs_the_same_experiment(saved, tmp_path):
    case = Explorer(saved).run('nested/batch')['cases'][0]
    command = case['reproduce']
    assert command[0] == 'raceplan-run'
    output = tmp_path / 'again/comparison.csv'
    arguments = [str(output) if value == 'NEW_FOLDER/comparison.csv' else value for value in command[1:]]
    assert experiment.main(arguments) == 0
    first = {row['episode_id']: row for row in read_csv(saved / 'nested/batch/comparison.csv')}
    for row in read_csv(output):
        assert row['tracking_rmse_m'] == first[row['episode_id']]['tracking_rmse_m']
        assert row['simulation_status'] == first[row['episode_id']]['simulation_status']


def test_unknown_runs_and_cases_are_rejected(saved):
    explorer = Explorer(saved)
    for run_id in ('../..', 'missing', 'suite/cases/demo', ''):
        with pytest.raises(UnknownItem):
            explorer.run(run_id)
    with pytest.raises(UnknownItem):
        explorer.case('suite', 'missing')
    assert sorted(case['id'] for case in explorer.run('suite')['cases']) == ['demo', 'open']


def test_server_serves_the_page_and_keeps_requests_local(client):
    response, body = client('/')
    assert response.status == 200 and b'RacePlan Explorer' in body
    shared = client('/?run=nested%2Fbatch&case=batch&seed=1&view=cmp&planners=&planners=fast%2Cv2&t=1.5')
    assert shared[0].status == 200 and shared[1] == body  # Shared links carry screen state only; the page restores it.
    policy = response.getheader('Content-Security-Policy')
    assert 'frame-ancestors' in policy and 'img-src' in policy and 'data:' in policy  # Checkbox ticks are data images.
    response, body = client('/api/runs')
    assert response.status == 200 and {run['id'] for run in json.loads(body)['runs']} == {'nested/batch', 'suite'}
    response, body = client('/api/run?id=nested%2Fbatch')
    assert response.status == 200 and json.loads(body)['cases'][0]['id'] == 'batch'
    assert client('/api/case?run=suite&id=demo')[0].status == 200
    assert client('/api/run?id=..%2F..')[0].status == 404
    assert client('/api/case?run=suite&id=..')[0].status == 404
    assert client('/static/index.html')[0].status == 404
    assert client('/', host='evil.example')[0].status == 403
    assert client('/', method='POST')[0].status == 404  # Only the job routes accept POST.


def test_tampered_saved_results_return_a_readable_error(saved, tmp_path):
    import shutil
    root = tmp_path / 'root'
    shutil.copytree(saved / 'nested/batch', root / 'batch')
    summary = root / 'batch/comparison.csv'
    summary.write_bytes(summary.read_bytes() + b'\n')
    server = make_server(root)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=30)
        connection.request('GET', '/api/run?id=batch')
        response = connection.getresponse()
        assert response.status == 422 and 'stale analysis input hash' in json.loads(response.read())['error']
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def _compare_case(saved):
    return Explorer(saved).run('nested/batch')['cases'][0]


def test_paired_delta_counts_every_candidate_once_and_matches_saved_pairs(saved):
    explorer = Explorer(saved)
    result = explorer.compare('nested/batch', 'batch', 'delta', metric='rmse')
    assert result['baseline'] == 'astar' and result['unit'] == 'm' and result['better'] == 'lower'
    assert [lane['planner'] for lane in result['lanes']] == ['dijkstra', 'example_exception']
    assert result['candidate'] == 4 and result['plotted'] + sum(result['excluded'].values()) == result['candidate']
    saved_pairs = {(row['planner'], row['simulation_seed']): row
                   for row in read_csv(saved / 'nested/batch/analysis/paired.csv')}
    for lane in result['lanes']:
        assert lane['candidate'] == 2
        assert len(lane['points']) + sum(lane['excluded'].values()) == 2
        for point in lane['points']:
            row = saved_pairs[(lane['planner'], str(point['seed']))]
            assert row['both_reached'] == 'True' and point['delta'] == float(row['delta_tracking_rmse_m'])
    failing = result['lanes'][1]
    assert failing['points'] == [] and failing['median'] is None  # Failed pairs are excluded, never drawn at 0.
    assert result['lanes'][0]['median'] == pytest.approx(
        sum(point['delta'] for point in result['lanes'][0]['points']) / len(result['lanes'][0]['points']))


def test_paired_delta_filters_report_their_own_exclusion_reason(saved):
    explorer = Explorer(saved)
    seed_only = explorer.compare('nested/batch', 'batch', 'delta', metric='time', seeds=[1])
    assert seed_only['candidate'] == 2 and all(point['seed'] == 1 for lane in seed_only['lanes'] for point in lane['points'])
    only_collisions = explorer.compare('nested/batch', 'batch', 'delta', outcomes=['collision'])
    assert only_collisions['plotted'] == 0 and only_collisions['excluded']['filtered_outcome'] == 4
    no_planners = explorer.compare('nested/batch', 'batch', 'delta', planners=[])
    assert no_planners['lanes'] == [] and no_planners['candidate'] == 0
    clearance = explorer.compare('nested/batch', 'batch', 'delta', metric='clearance')
    assert clearance['better'] == 'higher' and clearance['plotted'] + sum(clearance['excluded'].values()) == 4


def test_baseline_is_used_even_when_unselected_and_missing_baseline_is_reported(saved):
    case = _compare_case(saved)
    from raceplan.gui import analysis
    assert analysis.paired_delta(case, planners=['dijkstra'])['plotted'] == 2
    assert analysis.paired_delta({**case, 'baseline': None})['lanes'] == []
    missing = analysis.paired_delta({**case, 'pairs': []})
    assert missing['plotted'] == 0 and missing['excluded']['missing_pair'] == 4


def test_scatter_accounts_for_every_filtered_record(saved):
    result = Explorer(saved).compare('nested/batch', 'batch', 'scatter')
    assert result['records'] == 6
    assert result['plotted'] + result['not_reached'] + result['no_value'] + result['log_axis'] == 6
    assert result['not_reached'] == 2  # The failing custom planner keeps its rows in the count.
    saved_rows = {row['episode_id']: row for row in read_csv(saved / 'nested/batch/analysis/episodes.csv')}
    for point in result['points']:
        row = saved_rows[point['episode_id']]
        assert row['failure_class'] == 'reached' and point['y'] == float(row['tracking_rmse_m'])
        assert point['x'] == float(row['planning_time_ms'])
    runner = Explorer(saved).compare('nested/batch', 'batch', 'scatter', x='runner')
    assert runner['x_field'] == 'runner_planning_time_ms'
    assert runner['plotted'] + runner['not_reached'] + runner['no_value'] + runner['log_axis'] == 6
    assert Explorer(saved).compare('nested/batch', 'batch', 'scatter', seeds=[0])['records'] == 3


def test_compare_endpoints_validate_queries(client):
    base = '/api/compare/delta?run=nested%2Fbatch&case=batch'
    response, body = client(base + '&metric=rmse&planners=dijkstra&seeds=0&seeds=1')
    payload = json.loads(body)
    assert response.status == 200 and [lane['planner'] for lane in payload['lanes']] == ['dijkstra']
    assert client('/api/compare/scatter?run=nested%2Fbatch&case=batch&x=runner')[0].status == 200
    assert client(base + '&metric=bogus')[0].status == 400
    assert client(base + '&seeds=a')[0].status == 400
    assert client(base + '&seeds=0,1')[0].status == 400  # Values repeat the key; comma lists are not accepted.
    assert client('/api/compare/scatter?run=nested%2Fbatch&case=batch&x=bogus')[0].status == 400
    assert client('/api/compare/delta?run=nested%2Fbatch&case=missing')[0].status == 404
    assert client('/api/compare/delta?run=missing&case=batch')[0].status == 404


def test_outcome_filter_applies_to_the_compared_planner_with_exact_reasons(saved):
    explorer = Explorer(saved)
    reached = explorer.compare('nested/batch', 'batch', 'delta', outcomes=['reached'])
    dijkstra, failing = reached['lanes']
    assert len(dijkstra['points']) == 2 and sum(dijkstra['excluded'].values()) == 0
    assert failing['excluded'] == {'missing_pair': 0, 'filtered_outcome': 2, 'condition': 0, 'no_delta': 0}
    errors = explorer.compare('nested/batch', 'batch', 'delta', outcomes=['planning_error'])
    dijkstra, failing = errors['lanes']
    assert dijkstra['excluded']['filtered_outcome'] == 2 and dijkstra['points'] == []
    assert failing['excluded'] == {'missing_pair': 0, 'filtered_outcome': 0, 'condition': 2, 'no_delta': 0}


def test_blank_filters_select_nothing_and_names_may_contain_commas(client, saved):
    base = '/api/compare/delta?run=nested%2Fbatch&case=batch'
    assert json.loads(client(base + '&planners=')[1])['lanes'] == []
    assert json.loads(client(base + '&seeds=')[1])['candidate'] == 0
    blank = json.loads(client(base + '&outcomes=')[1])
    assert blank['plotted'] == 0 and blank['excluded']['filtered_outcome'] == 4
    repeated = json.loads(client(base + '&planners=dijkstra&planners=example_exception')[1])
    assert [lane['planner'] for lane in repeated['lanes']] == ['dijkstra', 'example_exception']
    from raceplan.gui import analysis
    case = {'planners': ['base', 'fast,v2', 'v2'], 'seeds': [0], 'baseline': 'base', 'pairs': [], 'episodes': []}
    assert [lane['planner'] for lane in analysis.paired_delta(case, planners=['fast,v2'])['lanes']] == ['fast,v2']


def test_delta_and_scatter_count_unusable_values_under_their_own_reason():
    from raceplan.gui import analysis
    def episode(planner, seed, **values):
        row = {'planner': planner, 'simulation_seed': seed, 'failure_class': 'reached', 'episode_id': f'{planner}:{seed}',
               'plan_id': planner, 'tracking_rmse_m': 0.1, 'planning_time_ms': 2.0, 'runner_planning_time_ms': 3.0}
        return {**row, **values}
    def pair(seed, **values):
        row = {'planner': 'b', 'baseline': 'a', 'simulation_seed': seed, 'both_reached': True, 'both_driven': True,
               'delta_tracking_rmse_m': 0.5, 'delta_completion_time_s': None, 'delta_driving_min_sampled_clearance_m': None}
        return {**row, **values}
    case = {'planners': ['a', 'b'], 'seeds': [0, 1, 2], 'baseline': 'a',
            'episodes': [episode(p, s) for p in 'ab' for s in range(3)],
            'pairs': [pair(0), pair(1, delta_tracking_rmse_m=None), pair(2, both_reached=False)]}
    result = analysis.paired_delta(case)
    assert result['plotted'] == 1 and result['candidate'] == 3
    assert result['excluded'] == {'missing_pair': 0, 'filtered_outcome': 0, 'condition': 1, 'no_delta': 1}
    assert {(row['planner'], row['seed']): row['reason'] for row in result['excluded_pairs']} == {
        ('b', 1): 'no_delta', ('b', 2): 'condition'}  # Each pair carries its own reason, not just the right totals.
    case['pairs'] = case['pairs'][:2]
    assert analysis.paired_delta(case)['excluded']['missing_pair'] == 1
    assert {(row['planner'], row['seed']): row['reason']
            for row in analysis.paired_delta(case, seeds=[0, 2])['excluded_pairs']} == {('b', 1): 'filtered_seed', ('b', 2): 'missing_pair'}
    case['episodes'][3] = episode('b', 0, planning_time_ms=None)
    case['episodes'][4] = episode('b', 1, planning_time_ms=0.0)
    case['episodes'][5] = episode('b', 2, failure_class='timeout')
    result = analysis.scatter(case)
    assert (result['records'], result['plotted'], result['no_value'], result['log_axis'], result['not_reached']) == (6, 3, 1, 1, 1)
    assert {(row['planner'], row['seed']): row['reason'] for row in result['excluded']} == {
        ('b', 0): 'no_value', ('b', 1): 'log_axis', ('b', 2): 'not_reached'}
    narrowed = analysis.scatter(case, planners=['b'], outcomes=['reached'])
    assert {(row['planner'], row['seed']): row['reason'] for row in narrowed['excluded']} == {
        ('a', 0): 'filtered_planner', ('a', 1): 'filtered_planner', ('a', 2): 'filtered_planner',
        ('b', 0): 'no_value', ('b', 1): 'log_axis', ('b', 2): 'filtered_outcome'}  # Planner filter wins over outcome filter.


def test_saved_baseline_survives_a_case_without_comparison_pairs(saved):
    suite_case = Explorer(saved).run('suite')['cases'][0]
    assert suite_case['planners'] == ['astar'] and suite_case['pairs'] == [] and suite_case['baseline'] == 'astar'
    result = Explorer(saved).compare('suite', suite_case['id'], 'delta')
    assert result['baseline'] == 'astar' and result['lanes'] == []


def test_every_episode_without_a_point_has_exactly_one_named_reason(saved):
    from collections import Counter
    from raceplan.gui.analysis import EXCLUSION_REASONS
    explorer, case = Explorer(saved), _compare_case(saved)
    episodes = sorted((row['planner'], row['simulation_seed']) for row in case['episodes'])
    pairs = sorted(key for key in episodes if key[0] != case['baseline'])
    for options in ({}, {'planners': ['astar', 'example_exception']}, {'seeds': [1]}, {'outcomes': ['reached']}, {'planners': []}):
        scatter = explorer.compare('nested/batch', 'batch', 'scatter', **options)
        shown = [(point['planner'], point['seed']) for point in scatter['points']]
        hidden = [(row['planner'], row['seed']) for row in scatter['excluded']]
        assert sorted(shown + hidden) == episodes, options  # Each saved episode is a point or one named exclusion.
        reasons = Counter(row['reason'] for row in scatter['excluded'])
        assert all(reasons[key] == scatter[key] for key in ('not_reached', 'no_value', 'log_axis'))
        assert scatter['records'] == len(episodes) - reasons['filtered_planner'] - reasons['filtered_seed'] - reasons['filtered_outcome']
        delta = explorer.compare('nested/batch', 'batch', 'delta', **options)
        shown = [(lane['planner'], point['seed']) for lane in delta['lanes'] for point in lane['points']]
        hidden = [(row['planner'], row['seed']) for row in delta['excluded_pairs']]
        assert sorted(shown + hidden) == pairs, options
        reasons = Counter(row['reason'] for row in delta['excluded_pairs'])
        assert {key: reasons[key] for key in EXCLUSION_REASONS} == delta['excluded']  # Same reasons as the lane counts.
    narrowed = explorer.compare('nested/batch', 'batch', 'scatter', planners=['astar', 'example_exception'])
    why = {(row['planner'], row['seed']): row['reason'] for row in narrowed['excluded']}
    assert why[('dijkstra', 0)] == 'filtered_planner' and why[('example_exception', 1)] == 'not_reached'
    why = {(row['planner'], row['seed']): row['reason']
           for row in explorer.compare('nested/batch', 'batch', 'delta', seeds=[1])['excluded_pairs']}
    assert why[('dijkstra', 0)] == 'filtered_seed' and why[('example_exception', 1)] == 'condition'


def test_coverage_counts_are_plain_integers_only():
    from raceplan.gui.data import _count
    assert _count(16) == 16 and _count(0) == 0
    for bad in ('<img src=x onerror=alert(1)>', None, 1.5, True, [1]):
        assert _count(bad) is None


def test_replay_puts_both_planners_on_one_clock_from_saved_samples(saved, monkeypatch):
    monkeypatch.setattr(AStarPlanner, 'plan', lambda *args, **kwargs: pytest.fail('replay must not plan'))
    monkeypatch.setattr('raceplan.simulator.run_episode', lambda *args, **kwargs: pytest.fail('replay must not simulate'))
    folder = saved / 'nested/batch'
    samples = {}
    for row in read_csv(folder / 'comparison_trajectory.csv'):
        samples.setdefault(row['episode_id'], []).append(round(float(row['time_s']), 5))
    outcomes = {row['episode_id']: row['failure_class'] for row in read_csv(folder / 'analysis/episodes.csv')}
    result = Explorer(saved).replay('nested/batch', 'batch', 'dijkstra', 'astar', 1)
    for side, episode_id in ((result['a'], 'dijkstra:1'), (result['b'], 'astar:1')):
        times = samples[episode_id]
        assert side['episode_id'] == episode_id and side['outcome'] == outcomes[episode_id]
        assert (side['start_s'], side['end_s'], side['samples']) == (times[0], times[-1], len(times))
        assert side['events'][-1] == [times[-1], 'ended'] and side['reason'] is None
    assert result['duration_s'] == max(samples['dijkstra:1'][-1], samples['astar:1'][-1])
    assert result['counts'] == {'slots': 2, 'episodes': 2, 'playable': 2}
    traces = Explorer(saved).case('nested/batch', 'batch')['traces']
    assert traces['dijkstra:1']['valid'] is True and traces['astar:1']['valid'] is True  # The page trusts this flag.

    failed = Explorer(saved).replay('nested/batch', 'batch', 'astar', 'example_exception', 0)
    assert failed['b']['outcome'] == 'planning_error' and failed['b']['reason'] == 'no_samples'
    assert failed['b']['events'] == [[0.0, 'no_record']] and failed['b']['end_s'] is None
    assert failed['duration_s'] == samples['astar:0'][-1]  # A missing record never stretches or shortens the clock.
    assert failed['counts'] == {'slots': 2, 'episodes': 2, 'playable': 1}


def test_replay_events_mark_waiting_driving_ended_and_unusable_records():
    from raceplan.gui import analysis
    def episode(planner):
        return {'planner': planner, 'simulation_seed': 0, 'episode_id': f'{planner}:0', 'plan_id': planner,
                'failure_class': 'reached'}
    def trace(times, x=None):
        return {'t': times, 'x': x or [0.0] * len(times), 'y': [0.0] * len(times)}
    case = {'planners': ['late', 'long', 'single', 'bad', 'empty', 'gone'], 'seeds': [0],
            'episodes': [episode(p) for p in ('late', 'long', 'single', 'bad', 'empty')]}
    traces = {'late:0': trace([1.0, 2.0, 3.0]), 'long:0': trace([0.0, 2.5, 5.0]), 'single:0': trace([0.0]),
              'bad:0': trace([0.0, 2.0, 1.0]), 'empty:0': trace([])}
    result = analysis.replay(case, traces, 'late', 'long', 0)
    assert result['a']['events'] == [[0.0, 'waiting'], [1.0, 'driving'], [3.0, 'ended']]
    assert result['b']['events'] == [[0.0, 'driving'], [5.0, 'ended']]
    assert result['duration_s'] == 5.0  # The later last sample, not the selected case's or other planners' ends.
    single = analysis.replay(case, traces, 'single', 'late', 0)
    assert single['a']['events'] == [[0.0, 'ended']] and single['duration_s'] == 3.0
    for planner, reason in (('bad', 'invalid_samples'), ('empty', 'no_samples'), ('gone', 'missing_episode')):
        side = analysis.replay(case, traces, planner, 'late', 0)['a']
        assert side['reason'] == reason and side['events'] == [[0.0, 'no_record']] and side['end_s'] is None
    for times, x in (([0.0, 1.0], [0.0, None]), ([0.0, None], None), ([-0.5, 1.0], None)):
        traces['bad:0'] = trace(times, x=x)
        assert analysis.replay(case, traces, 'bad', 'late', 0)['a']['reason'] == 'invalid_samples'
        assert analysis.trace_valid(traces['bad:0']) is False
    nothing = analysis.replay(case, traces, 'empty', 'gone', 0)
    assert nothing['duration_s'] == 0.0 and nothing['counts'] == {'slots': 2, 'episodes': 1, 'playable': 0}
    for a, b, seed in (('late', 'late', 0), ('late', 'nobody', 0), ('late', 'long', 7)):
        with pytest.raises(analysis.BadQuery):
            analysis.replay(case, traces, a, b, seed)


def test_replay_endpoint_validates_queries(client):
    base = '/api/compare/replay?run=nested%2Fbatch&case=batch'
    response, body = client(base + '&a=astar&b=dijkstra&seed=0')
    payload = json.loads(body)
    assert response.status == 200 and (payload['a']['planner'], payload['b']['planner'], payload['seed']) == ('astar', 'dijkstra', 0)
    for query in ('&a=astar&b=astar&seed=0', '&a=astar&b=nobody&seed=0', '&a=astar&b=dijkstra&seed=9',
                  '&a=astar&b=dijkstra&seed=x', '&a=astar&b=dijkstra'):
        assert client(base + query)[0].status == 400, query
    assert client('/api/compare/replay?run=nested%2Fbatch&case=missing&a=astar&b=dijkstra&seed=0')[0].status == 404
    assert client('/api/compare/replay?run=missing&case=batch&a=astar&b=dijkstra&seed=0')[0].status == 404


def _csv_rows(text):
    from io import StringIO
    return list(csv.reader(StringIO(text, newline='')))


def test_episode_export_is_the_saved_file_limited_to_the_table_filter(saved, client, monkeypatch):
    monkeypatch.setattr(AStarPlanner, 'plan', lambda *args, **kwargs: pytest.fail('export must not plan'))
    for target in ('raceplan.simulator.run_episode', 'raceplan.experiment.run_episode'):
        monkeypatch.setattr(target, lambda *args, **kwargs: pytest.fail('export must not simulate'))
    explorer = Explorer(saved)
    for run_id, case_id, path in (('nested/batch', 'batch', saved / 'nested/batch/analysis/episodes.csv'),
                                  ('suite', 'demo', saved / 'suite/cases/demo/analysis/episodes.csv'),
                                  ('suite', 'open', saved / 'suite/cases/open/analysis/episodes.csv')):
        header, *body = _csv_rows(path.read_text(encoding='utf-8-sig'))
        column = header.index('failure_class')
        for name, keep in (('all', lambda o: True), ('fail', lambda o: o != 'reached'), ('ok', lambda o: o == 'reached')):
            rows, _ = explorer.export_episodes(run_id, case_id, name)
            assert rows == [header, *(row for row in body if keep(row[column]))]  # Saved header, cell text and order.
    failures = explorer.export_episodes('nested/batch', 'batch', 'fail')[0]
    assert [row[failures[0].index('failure_class')] for row in failures[1:]] == ['planning_error', 'planning_error']

    response, body = client('/api/export/episodes.csv?run=nested%2Fbatch&case=batch&filter=fail')
    assert response.status == 200 and response.getheader('Content-Type') == 'text/csv; charset=utf-8'
    assert body.startswith(b'\xef\xbb\xbf') and body.count(b'\n') == body.count(b'\r\n')
    assert _csv_rows(body.decode('utf-8-sig')) == failures
    assert response.getheader('Content-Disposition') == (
        "attachment; filename=\"episodes.csv\"; filename*=UTF-8''nested-batch-batch-episodes-fail.csv")
    assert response.getheader('X-RacePlan-CSV-Formula-Risk') is None
    base = '/api/export/episodes.csv?run=nested%2Fbatch'
    assert client(base + '&case=batch&filter=bogus')[0].status == 400
    assert client(base + '&case=batch&filter=')[0].status == 400
    assert client(base + '&case=missing')[0].status == 404
    assert client('/api/export/episodes.csv?run=missing&case=batch')[0].status == 404
    for query in ('&case=batch&filter=ok&filter=fail', '&case=', '', '&case=batch&case=batch'):
        assert client(base + query)[0].status == 400, query  # Exports never guess between repeated or blank keys.
    assert client('/api/export/coverage.csv?run=nested%2Fbatch&case=batch')[0].status == 400
    assert client('/api/export/coverage.csv?run=')[0].status == 400


def test_coverage_export_keeps_failed_cases_and_unknown_counts(saved, tmp_path):
    import shutil
    header = ['case_id', 'status', 'expected_episode_count', 'raw_episode_count', 'included_episode_count',
              'missing_episode_count', 'failed_phase', 'error_type', 'error_message']
    assert Explorer(saved).export_coverage('nested/batch')[0] == [header, ['batch', 'complete', '6', '6', '6', '0', '', '', '']]

    root = tmp_path / 'root'
    shutil.copytree(saved / 'suite', root / 'suite')
    shutil.copytree(saved / 'nested/batch', root / 'failed')
    shutil.copytree(saved / 'nested/batch', root / 'blank')
    blank = root / 'blank/analysis/episodes.csv'
    lines = blank.read_bytes().split(b'\r\n') if b'\r\n' in blank.read_bytes() else blank.read_bytes().split(b'\n')
    blank.write_bytes(b'\r\n'.join([lines[0], b'', *lines[1:]]))  # Blank records pass validation, as csv.DictReader skips them.
    state_path = root / 'suite/suite.json'
    state = json.loads(state_path.read_text(encoding='utf-8'))
    message = 'boom, "quoted"\nsecond line'
    state['cases']['open'].update(status='failed', raw_episode_count=None, included_episode_count=0,
                                  failed_phase='execution_or_collection', error={'type': 'RuntimeError', 'message': message})
    state_path.write_text(json.dumps(state), encoding='utf-8')
    workflow_path = root / 'failed/workflow.json'
    workflow_state = json.loads(workflow_path.read_text(encoding='utf-8'))
    workflow_state.update(status='failed', failed_phase='analysis', error={'type': 'ValueError', 'message': '=cmd|x'})
    workflow_path.write_text(json.dumps(workflow_state), encoding='utf-8')

    explorer = Explorer(root)
    assert explorer.export_episodes('blank', 'batch', 'fail')[0] == Explorer(saved).export_episodes('nested/batch', 'batch', 'fail')[0]
    header_row, *rows = explorer.export_coverage('suite')[0]
    assert header_row == header
    saved_demo = next(row for row in csv.DictReader((saved / 'suite/coverage.csv').open(newline='', encoding='utf-8')) if row['case_id'] == 'demo')
    demo, failed = (dict(zip(header, row)) for row in rows)
    for field in ('status', 'expected_episode_count', 'raw_episode_count', 'included_episode_count', 'missing_episode_count'):
        assert demo[field] == saved_demo[field]
    expected = str(state['cases']['open']['expected_episode_count'])
    assert [failed[field] for field in header] == ['open', 'failed', expected, '', '0', expected,
                                                   'execution_or_collection', 'RuntimeError', message]
    # An unfinished workflow still reports its expected episodes from the manifest (3 planners x 2 seeds).
    assert explorer.export_coverage('failed')[0][1] == ['batch', 'failed', '6', '', '0', '6', 'analysis', 'ValueError', '=cmd|x']
    with pytest.raises(UnknownItem):
        explorer.export_episodes('failed', 'batch')

    server = make_server(root)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        def get(path):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=30)
            connection.request('GET', path)
            response = connection.getresponse()
            return response, response.read()
        response, body = get('/api/export/coverage.csv?run=suite')
        assert response.status == 200 and _csv_rows(body.decode('utf-8-sig'))[2][-1] == message  # Quotes and newline survive.
        response, body = get('/api/export/coverage.csv?run=failed')
        assert response.getheader('X-RacePlan-CSV-Formula-Risk') == '1'  # Flagged for the page, but kept as saved.
        assert _csv_rows(body.decode('utf-8-sig'))[1][-1] == '=cmd|x'
        # Another case's validated bytes in this case's place are refused, not served under this case's name.
        assert get('/api/export/episodes.csv?run=suite&case=demo')[0].status == 200  # Validated and cached first.
        (root / 'suite/cases/demo/analysis/episodes.csv').write_bytes((saved / 'suite/cases/open/analysis/episodes.csv').read_bytes())
        response, body = get('/api/export/episodes.csv?run=suite&case=demo')
        assert response.status == 422 and 'changed after it was validated' in json.loads(body)['error']
    finally:
        server.shutdown()
        server.server_close()


def test_formula_risk_ignores_numbers_and_download_names_drop_path_characters():
    from raceplan.gui.data import _download_name, _formula_risk
    assert not _formula_risk([['planner', 'delta'], ['astar', '-0.5'], ['b', '+3e-2'], ['c', ''], ['d', '-.5'], ['e', '1e5']])
    for cell in ('=1+1', '@SUM(A1)', ' -x', '\t=cmd', '+A1', '+INF', '\ufeff=x', '\u3000@x'):
        assert _formula_risk([['ok', cell]]), repr(cell)
    assert _formula_risk([['=header'], ['1']])  # Header cells are checked too.
    assert _download_name(('나의 실행/batch:1', 'case'), 'episodes-fail') == '나의 실행-batch-1-case-episodes-fail.csv'
    assert _download_name(('x' * 300,), 'coverage').endswith('x-coverage.csv')  # Long ids never cut the suffix.


SLOW_PLANNER = '''
import time
from raceplan.planners.base import Planner


class SlowPlanner(Planner):
    name = 'slow'

    def plan(self, grid, start, goal, *, timeout_s=None):
        time.sleep(120)
'''


class RunServer:
    """A run-enabled server over an empty results folder, with helpers that act like the page."""

    def __init__(self, root, timeout=120.0, scenarios=ROOT / 'scenarios'):
        self.server = make_server(root, scenarios=scenarios, run_timeout=timeout)
        self.port = self.server.server_address[1]
        Thread(target=self.server.serve_forever, daemon=True).start()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        connection.request(method, path, body=body, headers={'Host': f'127.0.0.1:{self.port}', **(headers or {})})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, json.loads(data) if response.getheader('Content-Type', '').startswith('application/json') else data

    def post(self, path, value, **override):
        headers = {'Origin': f'http://127.0.0.1:{self.port}', 'X-RacePlan-Token': self.server.token,
                   'Content-Type': 'application/json', **override}
        return self.request('POST', path, json.dumps(value).encode(), {k: v for k, v in headers.items() if v is not None})

    def wait(self, job_id, limit=120.0):
        import time
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            status, job = self.request('GET', f'/api/jobs/{job_id}')
            assert status == 200
            if job['status'] != 'running':
                return job
            time.sleep(0.2)
        raise AssertionError(f'job still running after {limit} s')

    def close(self):
        if self.server.jobs:
            self.server.jobs.shutdown()
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def runner(tmp_path):
    servers = []

    def start(**options):
        (tmp_path / 'results').mkdir(exist_ok=True)
        servers.append(RunServer(tmp_path / 'results', **options))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


def test_write_requests_need_this_pages_origin_token_and_json(runner, saved):
    from raceplan.gui.server import explorer_url
    server = runner()
    status, page = server.request('GET', '/')
    assert status == 200 and server.server.token.encode() not in page  # Fetching the page never hands out the token.
    assert explorer_url(server.server, 'my run') == f'http://127.0.0.1:{server.port}/?run=my%20run#token={server.server.token}'
    assert explorer_url(server.server, 's', True) == f'http://127.0.0.1:{server.port}/?run=s&scope=all#token={server.server.token}'
    status, options = server.request('GET', '/api/run-options')
    assert options['enabled'] and server.server.token not in json.dumps(options)
    ids = [item['id'] for item in options['scenarios']]
    assert 'demo.yaml' in ids and not any(name.endswith('_map.yaml') for name in ids)  # Map files are not scenarios.
    body = {'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0]}
    other = f'http://127.0.0.1:{server.port + 1}'
    for override, expected in (({'Origin': None}, 403), ({'Origin': 'http://evil.example'}, 403), ({'Origin': other}, 403),
                               ({'X-RacePlan-Token': None}, 403), ({'X-RacePlan-Token': 'x' * 43}, 403),
                               ({'Content-Type': 'text/plain'}, 415), ({'Host': 'evil.example'}, 403)):
        assert server.post('/api/jobs', body, **override)[0] == expected, override  # A cross-site form can do none of these.
    assert server.post('/api/jobs?x=1', body)[0] == 404
    page_headers = {'Origin': f'http://127.0.0.1:{server.port}', 'X-RacePlan-Token': server.server.token, 'Content-Type': 'application/json'}
    assert server.request('POST', '/api/jobs', b'{' * 20000, page_headers)[0] == 413
    assert server.request('POST', '/api/jobs', b'{"scenario"', page_headers)[0] == 400
    assert not (server.server.explorer.root / 'gui-runs').exists()  # Nothing started.

    read_only = RunServer(saved, scenarios=None)
    try:
        status, options = read_only.request('GET', '/api/run-options')
        assert status == 200 and options['enabled'] is False and options['reason']
        assert read_only.post('/api/jobs', body)[0] == 403
    finally:
        read_only.close()


def test_run_requests_are_checked_against_what_the_server_offers(runner, tmp_path):
    server = runner()
    good = {'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0]}
    planner_file = tmp_path / 'slow.py'
    planner_file.write_text(SLOW_PLANNER, encoding='utf-8')
    for change in ({'scenario': '../scenarios/demo.yaml'}, {'scenario': str(ROOT / 'scenarios/demo.yaml')},
                   {'scenario': 'corridor_width/gate_03_map.yaml'}, {'scenario': ['demo.yaml']}, {'planners': []},
                   {'planners': ['astar', 'astar']}, {'planners': ['rm -rf']}, {'planners': [['astar']]}, {'seeds': []},
                   {'seeds': [0, 0]}, {'seeds': [-1]}, {'seeds': [True]}, {'seeds': [2**31]}, {'seeds': ['1']}, {'seeds': [[1]]},
                   {'baseline': 'dijkstra'}, {'baseline': ['astar']}, {'extra': 1},
                   {'custom_planners': ['slow.py']}, {'custom_planners': [f'{tmp_path / "missing.py"}:Slow']},
                   {'custom_planners': [f'{planner_file}:not-a-name']}, {'custom_planners': ['\\\\host\\share\\p.py:P'], 'trust_user_code': True},
                   {'custom_planners': [f'{planner_file}:A', f'{planner_file}:A'], 'trust_user_code': True},
                   {'custom_planners': [f'{planner_file}:SlowPlanner']}, {'custom_planners': [f'{planner_file}:SlowPlanner'], 'trust_user_code': 'yes'}):
        status, reply = server.post('/api/jobs', {**good, **change})
        assert status == 400 and reply['error'], change
    assert server.post('/api/jobs', [1, 2])[0] == 400
    assert not (server.server.explorer.root / 'gui-runs').exists()  # Rejected requests never create folders or processes.
    assert server.request('GET', '/api/jobs/0123456789abcdef')[0] == 404
    assert server.post('/api/jobs/0123456789abcdef/cancel', {})[0] == 404


def test_started_comparison_runs_in_its_own_process_and_opens_as_a_saved_run(runner):
    import os
    server = runner()
    status, job = server.post('/api/jobs', {'scenario': 'demo.yaml', 'planners': ['astar', 'dijkstra'], 'seeds': [0], 'baseline': 'astar'})
    assert status == 202 and job['status'] == 'running' and job['run_id'].startswith('gui-runs/')
    assert server.server.jobs.current.process.pid != os.getpid()
    # The server's folder is not importable (-P); the runner is raceplan.workflow with patient state saves.
    assert server.server.jobs.current.command[1:4] == ['-P', '-m', 'raceplan.gui.workflow_runner']
    done = server.wait(job['id'])
    assert done['status'] == 'complete' and done['exit_code'] == 0, done['log'][-20:]
    assert done['workflow']['phases'] == {'experiment': 'complete', 'analysis': 'complete', 'report': 'complete'}
    assert any(line.startswith('workflow=') for line in done['log'])
    status, runs = server.request('GET', '/api/runs')
    assert job['run_id'] in {run['id'] for run in runs['runs']}
    status, run = server.request('GET', '/api/run?id=' + quote(job['run_id'], safe=''))
    assert status == 200 and run['cases'][0]['planners'] == ['astar', 'dijkstra'] and run['cases'][0]['baseline'] == 'astar'
    assert server.request('GET', '/api/run-options')[1]['current_job']['status'] == 'complete'


def test_slow_comparisons_are_single_cancellable_and_time_limited(runner, tmp_path):
    planner_file = tmp_path / 'slow.py'
    planner_file.write_text(SLOW_PLANNER, encoding='utf-8')
    body = {'scenario': 'demo.yaml', 'planners': ['astar'], 'custom_planners': [f'{planner_file}:SlowPlanner'], 'seeds': [0],
            'trust_user_code': True}
    server = runner()
    status, job = server.post('/api/jobs', body)
    assert status == 202
    assert server.post('/api/jobs', body)[0] == 409  # One comparison at a time.
    state_file = server.server.explorer.root / job['run_id'] / 'workflow.json'
    started_driving(server, job['id'])
    assert server.post(f'/api/jobs/{job["id"]}/cancel', {})[0] == 200
    done = server.wait(job['id'], limit=30)
    assert done['status'] == 'cancelled' and server.server.jobs.current.process.poll() is not None
    state = json.loads(state_file.read_text(encoding='utf-8'))
    assert state['status'] == 'failed' and state['error']['type'] == 'Cancelled' and state['phases']['experiment']['status'] == 'failed'

    limited = runner(timeout=10.0)
    status, job = limited.post('/api/jobs', body)
    done = limited.wait(job['id'], limit=40)
    assert done['status'] == 'timeout' and done['elapsed_s'] < 30 and limited.server.jobs.current.process.poll() is not None
    state = json.loads((limited.server.explorer.root / done['run_id'] / 'workflow.json').read_text(encoding='utf-8'))
    assert state['status'] == 'failed' and state['error']['type'] == 'Timeout' and state['failed_phase'] == 'experiment'
    assert state['phases']['experiment']['status'] == 'failed'  # Killed mid-run: recorded as failed, never complete or running.
    status, runs = limited.request('GET', '/api/runs')
    assert {run['id']: run['status'] for run in runs['runs']}[done['run_id']] == 'failed'

    status, job = server.post('/api/jobs', body)
    started_driving(server, job['id'])
    server.server.jobs.shutdown()  # Closing the explorer stops what it started and waits until the stop is recorded.
    state = json.loads((server.server.explorer.root / job['run_id'] / 'workflow.json').read_text(encoding='utf-8'))
    assert state['status'] == 'failed' and state['error']['type'] == 'Cancelled'
    assert server.server.jobs.get(job['id'])['status'] == 'cancelled'


def test_runner_retries_a_state_save_blocked_by_a_reader_but_not_forever(monkeypatch):
    from raceplan.gui import workflow_runner
    monkeypatch.setattr(workflow_runner, 'PAUSE_S', 0)
    calls = []

    def blocked_twice(path, state):
        calls.append(state)
        if len(calls) <= 2:
            raise PermissionError('target is open in another process')  # What os.replace hits on Windows.
    monkeypatch.setattr(workflow_runner, '_save_state', blocked_twice)
    workflow_runner._patient_save_state('workflow.json', {'status': 'complete'})
    assert len(calls) == 3

    def always_blocked(path, state):
        raise PermissionError('still open')
    monkeypatch.setattr(workflow_runner, '_save_state', always_blocked)
    with pytest.raises(PermissionError):
        workflow_runner._patient_save_state('workflow.json', {'status': 'complete'})


def started_driving(server, job_id, limit=30.0):
    """Wait until the workflow has written its state and entered the experiment phase."""
    import time
    deadline = time.monotonic() + limit
    while time.monotonic() < deadline:
        job = server.request('GET', f'/api/jobs/{job_id}')[1]
        if job['workflow'] and job['workflow']['current_phase'] == 'experiment':
            return
        time.sleep(0.2)
    raise AssertionError('workflow never reached the experiment phase')


TUNABLE_PLANNER = '''
import time
from pathlib import Path
from raceplan.planners import AStarPlanner
from raceplan.planners.base import Planner

DELAY = {delay}
MARK = {mark!r}


class Tunable(Planner):
    name = 'tunable'

    def plan(self, grid, start, goal, *, timeout_s=None):
        if MARK:
            Path(MARK).write_text('planning', encoding='utf-8')  # Tells the test this code is the one running.
        time.sleep(DELAY)
        return AStarPlanner().plan(grid, start, goal, timeout_s=timeout_s)
'''


def wait_for_file(path, limit=60.0):
    import time
    deadline = time.monotonic() + limit
    while not path.exists():
        assert time.monotonic() < deadline, f'{path.name} never appeared'
        time.sleep(0.1)


def test_watch_reruns_on_save_replacing_a_stale_run_until_stopped(runner, tmp_path):
    import time
    planner_file = tmp_path / 'tunable.py'
    mark = tmp_path / 'planning.txt'
    planner_file.write_text(TUNABLE_PLANNER.format(delay=120, mark=str(mark)), encoding='utf-8')
    body = {'scenario': 'demo.yaml', 'planners': ['astar'], 'custom_planners': [f'{planner_file}:Tunable'], 'seeds': [0],
            'trust_user_code': True}
    server = runner()
    server.server.jobs.watch_interval_s = 0.2
    assert server.post('/api/watch', {**body, 'custom_planners': []})[0] == 400  # Nothing to watch.
    status, started = server.post('/api/watch', body)
    assert status == 202 and started['watch']['active'] and started['job']['watch_run'] == 1
    first = started['job']
    assert server.post('/api/jobs', body)[0] == 409 and server.post('/api/watch', body)[0] == 409  # The watch owns the runner.
    wait_for_file(mark)  # The first run is inside the slow planner, so it really runs the old code.

    planner_file.write_text(TUNABLE_PLANNER.format(delay=0, mark=''), encoding='utf-8')  # Saving the fixed planner...
    deadline = time.monotonic() + 30
    while (current := server.request('GET', '/api/run-options')[1]['current_job'])['id'] == first['id']:
        assert time.monotonic() < deadline, 'saving the planner did not start a new run'
        time.sleep(0.2)
    assert current['trigger'] == 'change' and current['watch_run'] == 2
    stale = server.request('GET', f'/api/jobs/{first["id"]}')[1]
    assert stale['status'] == 'cancelled' and stale['workflow']['status'] == 'failed'  # ...stops the old code's run, on record,
    assert 'planner file changed' in stale['workflow']['error']['message']  # with the reason it was stopped.
    done = server.wait(current['id'])
    assert done['status'] == 'complete', done['log'][-20:]
    status, run = server.request('GET', '/api/run?id=' + quote(done['run_id'], safe=''))
    assert status == 200 and 'tunable' in run['cases'][0]['planners']

    status, stopped = server.post('/api/watch/stop', {})
    assert status == 200 and stopped['watch']['active'] is False and stopped['watch']['runs'] == 2
    planner_file.write_text(TUNABLE_PLANNER.format(delay=1, mark=''), encoding='utf-8')
    time.sleep(1.5)
    options = server.request('GET', '/api/run-options')[1]
    assert options['current_job']['id'] == done['id'] and options['watch']['runs'] == 2  # Stopped means no more runs.
    assert server.post('/api/watch/stop', {}, **{'X-RacePlan-Token': None})[0] == 403


def test_watch_reruns_once_per_settled_new_content_and_reports_a_dead_watch(tmp_path, monkeypatch):
    from raceplan.gui import jobs as jobs_module
    jobs = jobs_module.Jobs(tmp_path, ROOT / 'scenarios')
    launched = []
    monkeypatch.setattr(jobs, '_launch', lambda spec, trigger, watch: launched.append(trigger) or {'watch_run': len(launched)})
    watch = jobs_module.Watch({}, [tmp_path / 'p.py'], 0)
    # Saved 'a' at start; half-written 'b'; missing while an editor swaps the file; 'c' settled; 'd' settled;
    # 'c' briefly then back to 'd' (reverted); deleted and restored identical.
    polls = iter(['b', None, 'c', 'c', 'c', 'd', 'd', 'c', 'd', None, 'd', 'd'])

    def poll(paths, cache):
        mark = next(polls, StopIteration)
        if mark is StopIteration:
            raise RuntimeError('disk went away')
        return (mark,), None
    monkeypatch.setattr(jobs_module, '_fingerprint', poll)
    jobs._watch_loop(watch, ('a',), None)
    assert launched == ['change', 'change']  # Once for c and once for d; never for b, a revert or a restored copy.
    assert watch.active is False and 'disk went away' in watch.error  # A broken watch says so instead of "watching".

    stopped = jobs_module.Watch({}, [], 0)
    stopped.active = False
    with pytest.raises(jobs_module.Busy):  # "watch 끄기" between a change and its launch starts nothing.
        jobs_module.Jobs(tmp_path, ROOT / 'scenarios')._launch({}, 'change', stopped)


def test_watch_refuses_an_oversized_planner_file_before_running_it(runner, tmp_path, monkeypatch):
    from raceplan.gui import jobs as jobs_module
    planner_file = tmp_path / 'tunable.py'
    planner_file.write_text(TUNABLE_PLANNER.format(delay=0, mark=''), encoding='utf-8')
    monkeypatch.setattr(jobs_module, 'MAX_WATCH_BYTES', 64)
    server = runner()
    status, reply = server.post('/api/watch', {'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0],
                                               'custom_planners': [f'{planner_file}:Tunable'], 'trust_user_code': True})
    assert status == 400 and 'larger than' in reply['error']  # Refused on the first run too, not only on reruns.
    assert not (server.server.explorer.root / 'gui-runs').exists()
    assert server.request('GET', '/api/run-options')[1]['watch']['active'] is False


def test_watch_replaces_only_its_own_run(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from raceplan.gui import jobs as jobs_module

    def changed_once(owner):
        jobs = jobs_module.Jobs(tmp_path, ROOT / 'scenarios')
        cancelled = []
        monkeypatch.setattr(jobs, 'cancel', lambda job_id, note=None: cancelled.append(job_id))
        monkeypatch.setattr(jobs, '_launch', lambda spec, trigger, watch: {})
        watch = jobs_module.Watch({}, [tmp_path / 'p.py'], 0)
        jobs.current = SimpleNamespace(id='running', status='running', owner=owner(watch),
                                       waiter=SimpleNamespace(join=lambda timeout=None: None))
        polls = iter(['b', 'b'])

        def poll(paths, cache):
            mark = next(polls, None)
            if mark is None:
                watch.stop_event.set()
            return ('b',), None
        monkeypatch.setattr(jobs_module, '_fingerprint', poll)
        jobs._watch_loop(watch, ('a',), None)
        return cancelled

    assert changed_once(lambda watch: watch) == ['running']
    assert changed_once(lambda watch: None) == []  # A single run started in another tab after "watch 끄기" is left alone.


def test_nothing_starts_once_the_runner_is_shutting_down(tmp_path):
    from raceplan.gui.jobs import Busy, Jobs
    jobs = Jobs(tmp_path, ROOT / 'scenarios')
    jobs.shutdown()
    with pytest.raises(Busy):
        jobs.start({'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0]})
    assert not (tmp_path / 'gui-runs').exists()  # No child the shutdown would never stop.


def test_explorer_port_and_threads_cannot_be_taken_over(runner, monkeypatch):
    import os
    import socket
    import time
    from raceplan.gui import jobs as jobs_module, server as server_module
    server = runner()
    if os.name == 'nt':
        intruder = socket.socket()
        intruder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        with pytest.raises(OSError):  # Another socket cannot share the port and receive the page's token.
            intruder.bind(('127.0.0.1', server.port))
        intruder.close()
        taskkill = jobs_module._taskkill()
        assert os.path.isabs(taskkill) and Path(taskkill).is_file()  # Never a taskkill.exe from the current folder.
    monkeypatch.setattr(server_module, 'BODY_DEADLINE_S', 1.0)
    origin = f'127.0.0.1:{server.port}'
    head = (f'POST /api/jobs HTTP/1.1\r\nHost: {origin}\r\nOrigin: http://{origin}\r\nX-RacePlan-Token: {server.server.token}\r\n'
            'Content-Type: application/json\r\nContent-Length: 100\r\n\r\n').encode()

    def status_line(connection):
        reply = b''
        while b'\r\n' not in reply:
            chunk = connection.recv(4096)
            if not chunk:
                break
            reply += chunk
        connection.close()
        return reply.split(b'\r\n')[0]

    # A sender that trickles a byte every 0.2 s never trips a per-read timeout; only the whole-body deadline stops it.
    trickle = socket.create_connection(('127.0.0.1', server.port), timeout=10)
    trickle.sendall(head)
    started = time.monotonic()

    def keep_sending():
        try:
            for _ in range(30):
                trickle.sendall(b' ')
                time.sleep(0.2)
        except OSError:
            pass  # The server answered and closed the connection: that is the point.
    Thread(target=keep_sending, daemon=True).start()
    assert b' 408 ' in status_line(trickle) and time.monotonic() - started < 4

    short = socket.create_connection(('127.0.0.1', server.port), timeout=10)
    short.sendall(head + b'{"scen')
    short.shutdown(socket.SHUT_WR)  # The body ends before its declared length: a bad request, not a slow one.
    assert b' 400 ' in status_line(short)


def test_watch_command_runs_once_and_reports_the_saved_outcome(tmp_path, capsys):
    from raceplan.gui.data import Explorer
    from raceplan.gui.watch import main
    planner_file = tmp_path / 'tunable.py'
    planner_file.write_text(TUNABLE_PLANNER.format(delay=0, mark=''), encoding='utf-8')
    root = tmp_path / 'results'
    args = [f'{planner_file}:Tunable', '--scenario', str(ROOT / 'scenarios/demo.yaml'), '--output-root', str(root), '--once']
    root.mkdir()
    before = Explorer(root).runs_signature()
    assert main(args) == 0
    out = capsys.readouterr().out
    assert 'run: complete' in out and 'tunable 1/1 reached' in out and 'astar 1/1 reached' in out, out
    explorer = Explorer(root)
    assert explorer.runs_signature() != before  # The explorer's list refresh sees the new run.
    [saved_run] = explorer.runs()
    assert saved_run['id'].startswith('gui-runs/') and saved_run['status'] == 'complete'

    planner_file.write_text('raise RuntimeError("broken planner")\n', encoding='utf-8')
    assert main(args) == 1
    out = capsys.readouterr().out
    assert 'run: failed' in out and 'broken planner' in out, out


def test_exe_commands_reach_their_programs_and_hide_the_worker(monkeypatch, capsys):
    from raceplan.gui import app, server, watch, workflow_runner
    calls = []
    monkeypatch.setattr(server, 'main', lambda argv: calls.append(('gui', argv)) or 0)
    monkeypatch.setattr(watch, 'main', lambda argv: calls.append(('watch', argv)) or 0)
    monkeypatch.setattr(workflow_runner, 'main', lambda argv: calls.append(('worker', argv)) or 7)
    worker_args = ['C:/시나리오 폴더/demo.yaml', '--output-dir', 'D:\\out put\\run']
    assert app.main([]) == 0 and app.main(['gui', '--port', '0']) == 0 and app.main(['watch', 'p.py:P']) == 0
    assert app.main(['--workflow-worker', *worker_args]) == 7  # The worker's exit code is the process exit code.
    assert calls == [('gui', []), ('gui', ['--port', '0']), ('watch', ['p.py:P']), ('worker', worker_args)]
    assert app.main(['--help']) == 0
    usage = capsys.readouterr().out
    assert 'watch' in usage and 'gui' in usage and 'workflow-worker' not in usage  # Internal, not part of the interface.


def test_packaged_exe_uses_its_own_folder_and_a_fixed_results_folder(monkeypatch, tmp_path):
    import sys
    from raceplan.gui import frozen
    exe = tmp_path / 'Program Files' / 'RacePlan' / 'RacePlan.exe'
    args = ['C:/시나리오 폴더/demo.yaml', '--output-dir', 'D:\\out put']
    monkeypatch.setattr(sys, 'frozen', False, raising=False)
    assert frozen.workflow_command(args)[1:4] == ['-P', '-m', 'raceplan.gui.workflow_runner']
    assert frozen.default_results() == Path('results/raw') and frozen.default_scenarios() == Path('scenarios')
    monkeypatch.setattr(sys, 'frozen', True)
    monkeypatch.setattr(sys, 'executable', str(exe))
    monkeypatch.setattr(sys, '_MEIPASS', str(exe.parent / '_internal'), raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'Local'))
    assert frozen.workflow_command(args) == [str(exe), '--workflow-worker', *args]  # Arguments pass through unchanged.
    assert frozen.worker_folder(Path('caller folder')) == exe.parent / '_internal'
    assert frozen.default_scenarios() == exe.parent.resolve() / 'scenarios'  # Shipped next to the exe.
    assert frozen.default_results() == tmp_path / 'Local' / 'RacePlan' / 'results' / 'raw'  # Never the exe folder.


def test_runner_loads_nothing_unless_its_parent_signals_start(tmp_path):
    import subprocess
    import sys
    output = tmp_path / 'out'
    command = [sys.executable, '-P', '-m', 'raceplan.gui.workflow_runner', str(ROOT / 'scenarios/demo.yaml'),
               '--output-dir', str(output), '--planners', 'astar', '--simulation-seeds', '0', '--after-start-signal']
    done = subprocess.run(command, input=b'', capture_output=True, timeout=60, cwd=tmp_path)  # Parent gone: stdin closed.
    assert done.returncode == 3 and b'not started' in done.stderr and not output.exists()


SPAWNER_PLANNER = '''
import subprocess
import sys
from pathlib import Path
from raceplan.planners import AStarPlanner
from raceplan.planners.base import Planner


class Spawner(Planner):
    name = 'spawner'

    def plan(self, grid, start, goal, *, timeout_s=None):
        # Leaves a process behind, then finishes normally.
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        Path({pid_file!r}).write_text(str(child.pid), encoding='utf-8')
        return AStarPlanner().plan(grid, start, goal, timeout_s=timeout_s)
'''


def _alive(pid):
    """True while the process runs; errors other than "no such process" fail the test instead of reading as ended."""
    import ctypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        error = ctypes.get_last_error()
        assert error == 87, f'cannot query process {pid}: Windows error {error}'  # ERROR_INVALID_PARAMETER: it is gone.
        return False
    code = ctypes.c_ulong()
    try:
        assert kernel32.GetExitCodeProcess(handle, ctypes.byref(code)), f'cannot read the state of process {pid}'
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows job objects')
def test_processes_a_planner_leaves_behind_end_with_its_run(runner, tmp_path):
    import time
    pid_file = tmp_path / 'child.pid'
    planner_file = tmp_path / 'spawner.py'
    planner_file.write_text(SPAWNER_PLANNER.format(pid_file=str(pid_file)), encoding='utf-8')
    server = runner()
    status, job = server.post('/api/jobs', {'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0],
                                            'custom_planners': [f'{planner_file}:Spawner'], 'trust_user_code': True})
    assert status == 202
    done = server.wait(job['id'], limit=60)
    assert done['status'] == 'complete', done['log'][-20:]
    pid = int(pid_file.read_text(encoding='utf-8'))
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _alive(pid)  # Nothing the planner started outlives the comparison.


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows job objects')
def test_a_worker_that_cannot_be_contained_never_loads_a_planner(runner, tmp_path, monkeypatch):
    from raceplan.gui import winjob

    class Refused:
        def __init__(self):
            raise OSError('AssignProcessToJobObject failed')
    monkeypatch.setattr(winjob, 'KillOnCloseJob', Refused)
    marker = tmp_path / 'loaded.txt'
    planner_file = tmp_path / 'tunable.py'
    planner_file.write_text(TUNABLE_PLANNER.format(delay=0, mark=str(marker)), encoding='utf-8')
    server = runner()
    status, job = server.post('/api/jobs', {'scenario': 'demo.yaml', 'planners': ['astar'], 'seeds': [0],
                                            'custom_planners': [f'{planner_file}:Tunable'], 'trust_user_code': True})
    assert status == 202
    done = server.wait(job['id'], limit=30)
    assert done['status'] == 'failed' and done['record'].startswith('not started')  # Said why, on the job itself.
    assert not marker.exists()  # The planner never ran outside a job object.


def test_shutdown_stops_workers_first_and_keeps_its_deadline(tmp_path, monkeypatch):
    import threading
    import time
    from types import SimpleNamespace
    from raceplan.gui import jobs as jobs_module
    jobs = jobs_module.Jobs(tmp_path, ROOT / 'scenarios')
    stuck = threading.Event()
    started = time.monotonic()
    killed = []
    monkeypatch.setattr(jobs_module, '_kill_tree', lambda job: killed.append(time.monotonic() - started))
    watch = jobs_module.Watch({}, [], 0)
    watch.thread = threading.Thread(target=stuck.wait, daemon=True)  # A watch busy reading a slow file.
    watch.thread.start()
    worker = SimpleNamespace(id='w', status='running', cancel_requested=False, stop_note=None,
                             waiter=threading.Thread(target=stuck.wait, daemon=True))
    worker.waiter.start()
    jobs.watcher, jobs.jobs = watch, {'w': worker}
    try:
        jobs.shutdown(deadline_s=0.5)
        took = time.monotonic() - started
    finally:
        stuck.set()
    assert killed and killed[0] < 0.2  # Workers are stopped before anything is waited for...
    assert took < 1.5 and jobs.closed and watch.active is False  # ...and the whole wait fits the closing window.


def test_job_names_a_missing_module_only_as_the_cause_of_a_failure(tmp_path):
    import threading
    from raceplan.gui.jobs import Job
    job = Job('j', {'kind': 'workflow'}, tmp_path, 'run', [], 60)
    job.log.extend(["optional: No module named 'numba' (falling back)", 'planning...',
                    "ValueError: cannot load custom planner p.py:P: No module named 'scipy'"])
    lock = threading.Lock()
    assert job.snapshot(lock)['missing_module'] is None  # Still running: nothing to explain yet.
    job.status = 'failed'
    assert job.snapshot(lock)['missing_module'] == 'scipy'  # The last import error, not an earlier optional one.
    job.status = 'complete'
    assert job.snapshot(lock)['missing_module'] is None


def test_unwritable_results_folder_says_where_and_what_to_do(tmp_path, monkeypatch):
    from raceplan.gui.jobs import Jobs
    jobs = Jobs(tmp_path, ROOT / 'scenarios')
    monkeypatch.setattr(Path, 'mkdir', lambda self, *a, **k: (_ for _ in ()).throw(PermissionError(13, 'Access is denied')))
    with pytest.raises(OSError) as error:
        jobs._output('demo.yaml')
    assert str(tmp_path / 'gui-runs') in str(error.value) and '--output-root' in str(error.value)


@pytest.fixture(scope='module')
def two_case_suite(tmp_path_factory):
    """A finished suite with two cases, two planners and two noisy seeds, written by raceplan.suite itself."""
    root = tmp_path_factory.mktemp('suite_all')
    config = {'version': 1, 'planners': ['astar', 'dijkstra'], 'simulation_seeds': [0, 1], 'baseline': 'astar',
              'noise': {'steering_std_rad': 0.02, 'initial_position_std_m': 0.02},
              'cases': [{'id': 'demo', 'scenario': str(SCENARIO)},
                        {'id': 'open', 'scenario': str(ROOT / 'scenarios/validation_open.yaml')}]}
    (root / 'suite.yaml').write_text(yaml.safe_dump(config), encoding='utf-8')
    assert suite.main([str(root / 'suite.yaml'), '--output-dir', str(root / 'results/two')]) == 0
    return root / 'results'


def test_all_cases_totals_are_the_suites_own_saved_totals(two_case_suite, tmp_path):
    import shutil
    from raceplan.gui.suite_view import CHECKED_FIELDS
    overview = Explorer(two_case_suite).overview('two')
    assert overview['summary_check'] == {'status': 'match', 'count': 0, 'differences': []}
    saved = {row['planner']: row for row in read_csv(two_case_suite / 'two/summary.csv')}
    by_case = {(row['case_id'], row['planner']): row for row in read_csv(two_case_suite / 'two/case_summary.csv')}
    for entry in overview['leaderboard']:  # The page shows the suite's own numbers, field by field.
        for field in CHECKED_FIELDS:
            stored = saved[entry['planner']][field]
            assert (entry[field] is None and stored == '') or float(stored) == pytest.approx(entry[field], rel=1e-12), field
    assert {(case, planner) for case, planners in overview['matrix'].items() for planner in planners} == set(by_case)
    assert [row['case_id'] for row in overview['coverage']] == ['demo', 'open']
    assert len(overview['episodes']) == 8 and {episode['case'] for episode in overview['episodes']} == {'demo', 'open'}

    copy = tmp_path / 'copy'
    shutil.copytree(two_case_suite / 'two', copy / 'two')
    text = (copy / 'two/summary.csv').read_text(encoding='utf-8-sig')
    lines = text.splitlines()
    header, astar = lines[0].split(','), next(i for i, line in enumerate(lines) if line.startswith('astar,'))
    cells = lines[astar].split(',')
    cells[header.index('reached')] = str(int(cells[header.index('reached')]) + 1)  # A stale or edited saved total.
    lines[astar] = ','.join(cells)
    (copy / 'two/summary.csv').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    check = Explorer(copy).overview('two')['summary_check']
    assert check['status'] == 'mismatch' and {'file': 'summary.csv', 'row': 'astar', 'field': 'reached'} in [
        {key: item[key] for key in ('file', 'row', 'field')} for item in check['differences']]


def test_totals_pool_every_success_instead_of_taking_a_median_of_medians():
    from raceplan.gui.suite_view import totals

    def row(planner, outcome, rmse='', time='', collision='False', simulation='finished', planning='success'):
        return {'planner': planner, 'failure_class': outcome, 'tracking_rmse_m': rmse, 'completion_time_s': time,
                'collision': collision, 'simulation_status': simulation, 'planning_status': planning}
    cases = [{'id': 'a', 'planners': ['p'], 'rows': [row('p', 'reached', '1', '10'), row('p', 'reached', '2', '20'),
                                                     row('p', 'reached', '3', '30')]},
             {'id': 'b', 'planners': ['p'], 'rows': [row('p', 'reached', '10', '100'),
                                                     row('p', 'driving_collision', collision='True'),
                                                     row('p', 'timeout', simulation='timeout'),
                                                     row('p', 'planning_error', planning='planning_error')]}]
    [entry], matrix = totals(cases)
    assert entry['success_median_tracking_rmse_m'] == 2.5  # Median of medians would say 6.0.
    assert (entry['reached'], entry['episodes_recorded'], entry['collisions'], entry['timeouts'],
            entry['planning_failures'], entry['planning_errors']) == (4, 7, 1, 1, 1, 1)
    assert matrix['b']['p']['reached'] == 1 and matrix['a']['p']['success_median_completion_time_s'] == 20.0


def test_pooled_comparisons_keep_each_case_apart():
    from raceplan.gui.suite_view import pooled_delta, pooled_scatter

    def case(case_id, baseline, delta):
        episodes = [{'planner': name, 'simulation_seed': 0, 'failure_class': 'reached', 'episode_id': f'{name}:0',
                     'plan_id': name, 'planning_time_ms': 1.0, 'runner_planning_time_ms': 1.0, 'tracking_rmse_m': 0.1}
                    for name in ('base', 'other', 'p')]
        return {'id': case_id, 'planners': ['base', 'other', 'p'], 'seeds': [0], 'baseline': baseline, 'episodes': episodes,
                'pairs': [{'planner': name, 'simulation_seed': 0, 'both_reached': True, 'both_driven': True,
                           'delta_tracking_rmse_m': delta, 'delta_completion_time_s': 0.0,
                           'delta_driving_min_sampled_clearance_m': 0.0}
                          for name in ('base', 'other', 'p') if name != baseline]}
    same = pooled_delta([case('a', 'base', -0.1), case('b', 'base', -0.3)], planners=['p'])
    [lane] = same['lanes']
    assert same['baseline'] == 'base' and lane['median'] == pytest.approx(-0.2)
    assert sorted((point['case'], point['seed']) for point in lane['points']) == [('a', 0), ('b', 0)]  # Same seed, own case.
    assert {pair['case'] for pair in same['excluded_pairs'] if pair['reason'] == 'filtered_planner'} == {'a', 'b'}
    mixed = pooled_delta([case('a', 'base', -0.1), case('b', 'other', -0.3)], planners=['p'])
    assert mixed['baseline'] is None and mixed['baselines'] == ['base', 'other']
    assert sorted((lane['planner'], lane['baseline']) for lane in mixed['lanes']) == [('p', 'base'), ('p', 'other')]
    scatter = pooled_scatter([case('a', 'base', 0), case('b', 'base', 0)])
    assert scatter['plotted'] == 6 and {point['case'] for point in scatter['points']} == {'a', 'b'}
    with pytest.raises(BadQuery):
        pooled_delta([], metric='nope')


def test_all_cases_endpoints_and_export(two_case_suite):
    server = make_server(two_case_suite)
    Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    def get(path):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=30)
        connection.request('GET', path, headers={'Host': f'127.0.0.1:{port}'})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, body
    try:
        status, body = get('/api/run?id=two')
        run = json.loads(body)
        assert status == 200 and run['kind'] == 'suite' and run['cases'][0]['map_label'] == 'maps/demo'
        assert get('/api/suite/overview?run=two')[0] == 200 and get('/api/suite/overview?run=two&case=demo')[0] == 400
        status, body = get('/api/compare/delta?run=two&scope=all&metric=rmse')
        delta = json.loads(body)
        assert status == 200 and delta['candidate'] == 4 and all('case' in pair for pair in delta['excluded_pairs'])
        assert (delta['case_ids'], delta['cases_listed']) == (['demo', 'open'], 2)
        for bad in ('/api/compare/delta?run=two&scope=all&case=demo', '/api/compare/scatter?run=two&scope=some',
                    '/api/export/suite-episodes.csv?run=two&case=demo'):
            assert get(bad)[0] == 400, bad
        status, body = get('/api/export/suite-episodes.csv?run=two&filter=all')
        rows = _csv_rows(body.decode('utf-8-sig'))
        demo = read_csv(two_case_suite / 'two/cases/demo/analysis/episodes.csv')
        assert status == 200 and rows[0][0] == 'case_id' and len(rows) == 1 + 8
        assert rows[1][0] == 'demo' and rows[1][1:] == list(demo[0].values())  # Saved cell text, case order then file order.
    finally:
        server.shutdown()
        server.server_close()


def test_all_cases_view_is_only_for_suites(saved):
    explorer = Explorer(saved)
    assert explorer.run('nested/batch')['kind'] == 'batch'
    for call in (lambda: explorer.overview('nested/batch'), lambda: explorer.compare_all('nested/batch', 'delta'),
                 lambda: explorer.export_suite_episodes('nested/batch')):
        with pytest.raises(BadQuery):
            call()


def test_new_run_folders_say_which_scenario_they_ran(tmp_path):
    from raceplan.gui.jobs import run_slug
    for family in ('offset_islands', 'staggered_windows'):
        (tmp_path / family).mkdir()
        (tmp_path / family / 'q0.yaml').write_text((SCENARIO.read_text(encoding='utf-8')
                                                    .replace('name: demo-gap', 'name: q0')
                                                    .replace('../maps/', str(ROOT / 'maps').replace('\\', '/') + '/')),
                                                   encoding='utf-8')
    # Same file name in two folders and a name that only repeats it: the folder keeps them apart.
    assert run_slug(tmp_path, 'offset_islands/q0.yaml') == 'offset_islands-q0'
    assert run_slug(tmp_path, 'staggered_windows/q0.yaml') == 'staggered_windows-q0'
    assert run_slug(ROOT / 'scenarios', 'demo.yaml') == 'demo-gap'  # The scenario's own name when it says more.
    # raceplan-gui watch passes the scenario's own folder and its bare file name.
    assert run_slug(tmp_path / 'offset_islands', 'q0.yaml') == 'offset_islands-q0'
    assert run_slug(tmp_path / 'staggered_windows', 'q0.yaml') == 'staggered_windows-q0'


def test_one_overview_answer_is_one_loaded_snapshot(two_case_suite, monkeypatch):
    explorer = Explorer(two_case_suite)
    calls = []
    real = Explorer._loaded
    monkeypatch.setattr(Explorer, '_loaded', lambda self, run_id: calls.append(run_id) or real(self, run_id))
    overview = explorer.overview('two')
    assert calls == ['two']  # Totals, rows, case list and coverage cannot come from two different loads.
    assert [case['id'] for case in overview['run']['cases']] == list(overview['matrix']) == ['demo', 'open']
    assert overview['run']['coverage'] == overview['coverage']


def test_saved_totals_are_checked_once_the_suite_has_written_them(two_case_suite, tmp_path):
    import shutil
    for status, phase, finished, expected in (('partial', 'complete', True, 'match'), ('interrupted', 'complete', True, 'match'),
                                              ('running', 'cases', False, 'not_final'), ('failed', 'cases', True, 'missing')):
        copy = tmp_path / status / 'two'
        shutil.copytree(two_case_suite / 'two', copy)
        state = json.loads((copy / 'suite.json').read_text(encoding='utf-8'))
        state.update(status=status, phase=phase)
        if not finished:
            state.pop('finished_at_utc')
        (copy / 'suite.json').write_text(json.dumps(state), encoding='utf-8')
        assert Explorer(copy.parent).overview('two')['summary_check']['status'] == expected, status


def test_saved_totals_that_a_dict_reader_would_mend_are_unreadable(two_case_suite, tmp_path):
    import shutil
    for name, mend in (('repeated', lambda lines: [lines[0] + ',reached', *[line + ',0' for line in lines[1:]]]),
                       ('short', lambda lines: [lines[0], lines[1].rsplit(',', 1)[0], *lines[2:]]),
                       ('quote', lambda lines: [*lines[:-1], '{},"{}'.format(*lines[-1].rsplit(',', 1))])):
        copy = tmp_path / name / 'two'
        shutil.copytree(two_case_suite / 'two', copy)
        lines = (copy / 'summary.csv').read_text(encoding='utf-8-sig').splitlines()
        (copy / 'summary.csv').write_text('\n'.join(mend(lines)) + '\n', encoding='utf-8')
        check = Explorer(copy.parent).overview('two')['summary_check']
        assert check['status'] == 'missing' and 'summary.csv' in check['message'], name


def test_a_state_that_changes_while_loading_is_read_again(two_case_suite, tmp_path, monkeypatch):
    import shutil
    from raceplan.gui import data
    shutil.copytree(two_case_suite / 'two', tmp_path / 'two')
    path, real, calls = tmp_path / 'two/suite.json', data._load, []

    def load(reader, folder):
        result = real(reader, folder)
        calls.append(1)
        if len(calls) == 1:  # The suite writes its state again between our two reads.
            state = json.loads(path.read_text(encoding='utf-8'))
            path.write_text(json.dumps({**state, 'note': 'rewritten'}), encoding='utf-8')
        return result
    monkeypatch.setattr(data, '_load', load)
    overview = Explorer(tmp_path).overview('two')
    assert len(calls) == 2 and overview['summary_check']['status'] == 'match'


def test_saved_totals_check_flags_repeated_extra_and_missing_columns(two_case_suite):
    from raceplan.gui.suite_view import check_saved, totals
    explorer = Explorer(two_case_suite)
    entry = explorer._loaded('two')
    leaderboard, matrix = totals([{'id': case['id'], 'planners': list(case['manifest']['planners']), 'rows': case['episodes']}
                                  for case in entry['cases'].values()])
    summary = read_csv(two_case_suite / 'two/summary.csv')
    by_case = read_csv(two_case_suite / 'two/case_summary.csv')
    assert check_saved(leaderboard, matrix, summary, by_case) == []
    found = check_saved(leaderboard, matrix, summary + [dict(summary[0])],
                        by_case + [{**by_case[0], 'case_id': 'never_ran'}])
    assert {(item['file'], item['saved']) for item in found} == {('summary.csv', 'repeated row'), ('case_summary.csv', 'row')}
    no_column = [{key: value for key, value in row.items() if key != 'success_median_tracking_rmse_m'} for row in summary]
    assert {item['field'] for item in check_saved(leaderboard, matrix, no_column, by_case)} == {'success_median_tracking_rmse_m'}


def test_a_reached_episode_without_a_finite_value_is_an_error_not_a_dropped_sample():
    from raceplan.gui.suite_view import totals
    row = {'planner': 'p', 'simulation_seed': '3', 'failure_class': 'reached', 'tracking_rmse_m': 'nan',
           'completion_time_s': '5', 'collision': 'False', 'simulation_status': 'finished', 'planning_status': 'success'}
    with pytest.raises(ValueError, match="case a: p seed 3 .*tracking_rmse_m is 'nan'"):
        totals([{'id': 'a', 'planners': ['p'], 'rows': [row]}])


SECOND_CASE_SLOW = '''
import time
from pathlib import Path
from raceplan.planners import AStarPlanner

MARK = Path(__file__).with_name('first-case.done')


class SecondCaseSlow(AStarPlanner):
    name = 'second_slow'

    def plan(self, grid, start, goal, *, timeout_s=None):
        if MARK.exists():  # Every case after the first one hangs until stopped.
            time.sleep(120)
        MARK.write_text('done', encoding='utf-8')
        return super().plan(grid, start, goal, timeout_s=timeout_s)
'''


def test_research_conditions_run_as_a_suite_and_open_as_all_cases(runner):
    server = runner()
    body = {'scenarios': ['demo.yaml', 'validation_open.yaml'], 'planners': ['astar'], 'seeds': [0, 1],
            'noise': {'steering_std_rad': 0.02, 'initial_position_std_m': 0.02}}
    status, job = server.post('/api/jobs', body)
    assert status == 202 and job['kind'] == 'suite' and '-plus1-' in job['run_id']
    assert server.server.jobs.current.command[4] == '--suite'
    done = server.wait(job['id'])
    assert done['status'] == 'complete', done['log'][-20:]
    assert done['suite']['counts'] == {'complete': 2} and done['suite']['coverage']['included_episode_count'] == 4
    folder = server.server.explorer.root / done['run_id']
    resolved = json.loads((folder / 'resolved_config.json').read_text(encoding='utf-8'))
    assert resolved['settings']['noise']['steering_std_rad'] == 0.02 and resolved['settings']['baseline'] == 'astar'
    assert [case['id'] for case in resolved['cases']] == ['demo', 'validation_open']
    status, overview = server.request('GET', '/api/suite/overview?run=' + quote(done['run_id'], safe=''))
    assert status == 200 and overview['summary_check']['status'] == 'match'
    assert [(row['planner'], row['episodes_recorded']) for row in overview['leaderboard']] == [('astar', 4)]
    # One scenario without noise still runs the single comparison it always did.
    status, single = server.post('/api/jobs', {'scenarios': ['demo.yaml'], 'planners': ['astar'], 'seeds': [0]})
    assert status == 202 and single['kind'] == 'workflow' and single['scenario'] == 'demo.yaml'  # Old consumers keep it.
    assert server.wait(single['id'])['status'] == 'complete'
    assert (server.server.explorer.root / single['run_id'] / 'workflow.json').is_file()


def test_research_run_requests_are_checked_before_anything_starts(runner, tmp_path):
    from raceplan.gui.jobs import JobError, Jobs
    server = runner()
    good = {'scenarios': ['demo.yaml', 'validation_open.yaml'], 'planners': ['astar'], 'seeds': [0]}
    for change in ({'scenario': 'demo.yaml'}, {'scenarios': []}, {'scenarios': ['demo.yaml', 'demo.yaml']},
                   {'scenarios': ['demo.yaml', 'missing.yaml']}, {'scenarios': 'demo.yaml'},
                   {'noise': {'wind': 1}}, {'noise': {'steering_std_rad': -0.1}}, {'noise': {'steering_std_rad': True}},
                   {'noise': {'steering_std_rad': '0.1'}}, {'noise': [0.1]}):
        status, reply = server.post('/api/jobs', {**good, **change})
        assert status == 400 and reply['error'], change
    assert server.post('/api/jobs', {key: value for key, value in good.items() if key != 'scenarios'})[0] == 400
    assert not (server.server.explorer.root / 'gui-runs').exists()
    jobs = Jobs(tmp_path, ROOT / 'scenarios', allowed=[f's{index}.yaml' for index in range(17)])
    with pytest.raises(JobError, match='1-16'):
        jobs.validate({**good, 'scenarios': [f's{index}.yaml' for index in range(17)]})
    with pytest.raises(JobError, match='too large'):  # 16 scenarios x 13 seeds = 208 runs per planner.
        jobs.validate({**good, 'scenarios': [f's{index}.yaml' for index in range(16)], 'seeds': list(range(13))})
    for value in (float('inf'), float('nan'), 10**400):
        with pytest.raises(JobError, match='noise'):
            jobs.validate({**good, 'scenarios': ['s0.yaml'], 'noise': {'steering_std_rad': value}})
    real = Jobs(tmp_path, ROOT / 'scenarios')
    noisy = real.validate({**good, 'scenarios': ['demo.yaml'], 'noise': {'steering_std_rad': 0.01}})
    assert noisy['kind'] == 'suite' and noisy['noise']['initial_speed_std_mps'] == 0.0  # Noise alone makes a suite.
    aliases = Jobs(tmp_path, ROOT / 'scenarios', allowed=['demo.yaml', 'corridor_width/../demo.yaml'])
    with pytest.raises(JobError, match='different files'):  # One file under two names is one case, not two.
        aliases.validate({**good, 'scenarios': ['demo.yaml', 'corridor_width/../demo.yaml']})


def test_suite_case_ids_are_what_the_suite_accepts():
    from raceplan.gui.jobs import case_ids
    names = ['a/q0.yaml', 'b/q0.yaml', 'A/q0.yaml', 'con.yaml', '한글.yaml', '지도.yaml']
    assert case_ids(names) == ['a-q0', 'b-q0', 'A-q0-2', 'con-case', 'case', 'case-2']


def test_a_stopped_suite_keeps_its_finished_cases_and_says_what_did_not_run(runner, tmp_path):
    planner_file = tmp_path / 'second.py'
    planner_file.write_text(SECOND_CASE_SLOW, encoding='utf-8')
    server = runner()
    status, job = server.post('/api/jobs', {'scenarios': ['validation_open.yaml', 'demo.yaml', 'corridor_width/gate_03.yaml'],
                                            'planners': ['astar'], 'custom_planners': [f'{planner_file}:SecondCaseSlow'],
                                            'seeds': [0], 'trust_user_code': True})
    assert status == 202, job
    import time
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        current = server.request('GET', f'/api/jobs/{job["id"]}')[1]
        if (current['suite'] or {}).get('current') == 'demo' and (current['workflow'] or {}).get('current_phase') == 'experiment':
            break
        time.sleep(0.2)
    else:
        raise AssertionError('the suite never reached its second case')
    assert server.post(f'/api/jobs/{job["id"]}/cancel', {})[0] == 200
    done = server.wait(job['id'], limit=30)
    assert done['status'] == 'cancelled'
    folder = server.server.explorer.root / done['run_id']
    state = json.loads((folder / 'suite.json').read_text(encoding='utf-8'))
    statuses = {case_id: record['status'] for case_id, record in state['cases'].items()}
    assert state['status'] == 'interrupted' and state['error']['type'] == 'Cancelled'
    assert statuses == {'validation_open': 'complete', 'demo': 'failed', 'corridor_width-gate_03': 'not_run'}
    assert state['coverage']['completed_cases'] == 1 and state['coverage']['not_run_cases'] == 1
    case_state = json.loads((folder / 'cases/demo/workflow.json').read_text(encoding='utf-8'))
    assert case_state['status'] == 'failed' and case_state['error']['type'] == 'Cancelled'
    assert not (folder / 'summary.csv').exists()  # No totals are made up for a suite that did not finish.
    status, overview = server.request('GET', '/api/suite/overview?run=' + quote(done['run_id'], safe=''))
    assert status == 200 and [case['id'] for case in overview['run']['cases']] == ['validation_open']
    assert overview['summary_check']['status'] == 'missing'


PLANNER_CLASSES = '''
from pathlib import Path
Path(__file__).with_name('ran.txt').write_text('executed')  # Must never happen while scanning.
import raceplan.planners as rp
from raceplan.planners import AStarPlanner as Fast
from raceplan.planners.base import Planner
from helpers import Base


class Direct(Planner):
    pass


class ViaAlias(Fast):
    pass


class ViaModule(rp.DijkstraPlanner):
    pass


class Later(Child):
    pass


class Child(Direct):
    pass


class Elsewhere(Base):
    pass


class Twice(Planner):
    pass


class Twice(Planner):
    pass


class Config:
    pass
'''


def test_planner_classes_are_found_without_running_the_file(tmp_path, runner):
    from raceplan.gui.planner_scan import ScanError, classes
    source = tmp_path / '내 플래너.py'
    source.write_text(PLANNER_CLASSES, encoding='utf-8')
    found = classes(str(source))
    assert [(item['name'], item['base']) for item in found['planners']] == [
        ('Direct', 'Planner'), ('ViaAlias', 'AStarPlanner'), ('ViaModule', 'DijkstraPlanner'), ('Child', 'Direct'),
        ('Twice', 'Planner')]  # The last definition of a name is the one a run loads.
    # Later derives from Child before Child exists (that file would not even load); Elsewhere's base is another module's.
    assert {item['name'] for item in found['other']} == {'Later', 'Elsewhere', 'Config'}
    (tmp_path / 'rebound.py').write_text('from raceplan.planners import Planner\n\n\nclass A(Planner):\n    pass\n\n\n'
                                          'A = None\nPlanner = object\n\n\nclass B(Planner):\n    pass\n', encoding='utf-8')
    rebound = classes(str(tmp_path / 'rebound.py'))
    assert rebound['planners'] == [] and {item['name'] for item in rebound['other']} == {'A', 'B'}
    assert not (tmp_path / 'ran.txt').exists()
    (tmp_path / 'broken.py').write_text('class A(:\n', encoding='utf-8')
    for bad in (str(tmp_path / 'broken.py'), str(tmp_path / 'missing.py'), str(tmp_path), '\\\\host\\share\\p.py', ''):
        with pytest.raises(ScanError):
            classes(bad)
    server = runner()
    status, reply = server.post('/api/planner-classes', {'file': str(source)})
    assert status == 200 and reply['file'] == str(source.resolve()) and len(reply['planners']) == 5
    assert server.post('/api/planner-classes', {'file': str(tmp_path / 'broken.py')})[0] == 400
    assert server.post('/api/planner-classes', {'path': str(source)})[0] == 400
    assert server.post('/api/planner-classes', {'file': str(source)}, **{'X-RacePlan-Token': None})[0] == 403


def test_watch_command_runs_several_scenarios_with_noise(tmp_path, capsys):
    from raceplan.gui import watch
    planner_file = tmp_path / 'p.py'
    planner_file.write_text('from raceplan.planners import AStarPlanner\n\n\nclass Mine(AStarPlanner):\n    name = "mine"\n',
                            encoding='utf-8')
    code = watch.main([f'{planner_file}:Mine', '--scenario', str(ROOT / 'scenarios/demo.yaml'),
                       '--scenario', str(ROOT / 'scenarios/validation_open.yaml'), '--steering-std-rad', '0.01',
                       '--output-root', str(tmp_path / 'out'), '--once'])
    printed = capsys.readouterr().out
    assert code == 0 and '2/2 case(s) complete' in printed and 'mine' in printed, printed
    [run] = (tmp_path / 'out/gui-runs').glob('2*')
    assert json.loads((run / 'suite.json').read_text(encoding='utf-8'))['status'] == 'complete'
    for name, seed in (('a', 1), ('b', 2)):  # Different own seeds: which ones to use must be said.
        (tmp_path / name).mkdir()
        (tmp_path / name / 'q0.yaml').write_text(SCENARIO.read_text(encoding='utf-8').replace('simulation_seed: 0', f'simulation_seed: {seed}')
                                                .replace('../maps/', str(ROOT / 'maps').replace('\\', '/') + '/'), encoding='utf-8')
    with pytest.raises(SystemExit):
        watch.main([f'{planner_file}:Mine', '--scenario', str(tmp_path / 'a/q0.yaml'), '--scenario', str(tmp_path / 'b/q0.yaml'),
                    '--output-root', str(tmp_path / 'out'), '--once'])
    assert 'give --seeds' in capsys.readouterr().err


def test_a_suite_stopped_before_its_first_save_is_recorded_as_nothing_run(tmp_path):
    from types import SimpleNamespace
    from raceplan.gui.jobs import Jobs
    output = tmp_path / 'run'
    output.mkdir()  # The suite made its folder (and config files) but had not saved suite.json yet.
    job = SimpleNamespace(output=output, timeout_s=60.0, stop_note=None, record=None,
                          process=SimpleNamespace(returncode=1),
                          spec={'kind': 'suite', 'scenarios': ['demo.yaml', 'validation_open.yaml'], 'planners': ['astar'],
                                'custom_planners': [], 'seeds': [0, 1]})
    Jobs._record_stop(job, 'cancelled')
    state = json.loads((output / 'suite.json').read_text(encoding='utf-8'))
    assert state['status'] == 'interrupted' and state['error']['type'] == 'Cancelled'
    assert {record['status'] for record in state['cases'].values()} == {'not_run'}
    assert state['coverage']['expected_episode_count'] == 4 and state['coverage']['included_episode_count'] == 0
    assert 'recorded as interrupted' in job.record
    status, overview = 200, Explorer(tmp_path).overview('run')  # It opens, with nothing included and why.
    assert overview['run']['cases'] == [] and [row['status'] for row in overview['coverage']] == ['not_run', 'not_run']


def test_a_planner_file_saved_during_a_suite_is_reported(tmp_path):
    from raceplan.gui.suite_view import planner_versions
    provenance = {'input_sha256': {'C:/p.py': 'a' * 64, 'C:/scenario.yaml': 'b' * 64}}
    same = {'custom_planner_sources': {'mine': {'path': 'C:/p.py', 'sha256': 'a' * 64, 'class': 'Mine'}}}
    later = {'custom_planner_sources': {'mine': {'path': 'C:/p.py', 'sha256': 'c' * 64, 'class': 'Mine'}}}
    assert planner_versions(provenance, [('one', same), ('two', same)]) == {'checked': 2, 'mismatches': []}
    found = planner_versions(provenance, [('one', same), ('two', later)])
    assert found['mismatches'] == [{'case': 'two', 'planner': 'mine', 'path': 'C:/p.py', 'recorded': 'a' * 12, 'ran': 'c' * 12}]
    assert planner_versions(provenance, [('one', {})]) == {'checked': 0, 'mismatches': []}  # Built-in planners only.


def test_watch_counts_only_the_cases_the_suite_completed(tmp_path):
    from raceplan.gui.watch import _outcomes
    run = tmp_path / 'gui-runs/s'
    for case_id, rows in (('done', ['reached', 'driving_collision']), ('failed_later', ['reached', 'reached'])):
        (run / 'cases' / case_id / 'analysis').mkdir(parents=True)
        (run / 'cases' / case_id / 'analysis/episodes.csv').write_text(
            'planner,failure_class\n' + ''.join(f'astar,{row}\n' for row in rows), encoding='utf-8')
    (run / 'suite.json').write_text(json.dumps({'cases': {'done': {'status': 'complete'},
                                                          'failed_later': {'status': 'failed'}}}), encoding='utf-8')
    assert _outcomes(tmp_path, 'gui-runs/s') == '1/2 case(s) complete: astar 1/2 reached'


def test_odd_planner_version_records_are_reported_not_fatal():
    from raceplan.gui.suite_view import planner_versions
    source = {'custom_planner_sources': {'mine': {'path': 'C:/p.py', 'sha256': 'a' * 64}}}
    for provenance in ({'input_sha256': None}, {'input_sha256': []}, None, []):
        assert planner_versions(provenance, [('one', source)])['mismatches'][0]['recorded'] == ''
    assert planner_versions({}, [('one', {'custom_planner_sources': None}), ('two', None)]) == {'checked': 0, 'mismatches': []}


def test_an_annotation_does_not_hide_the_planner_base(tmp_path):
    from raceplan.gui.planner_scan import classes
    (tmp_path / 'a.py').write_text('from raceplan.planners import Planner\nPlanner: type\n\n\nclass Mine(Planner):\n    pass\n',
                                   encoding='utf-8')
    assert [item['name'] for item in classes(str(tmp_path / 'a.py'))['planners']] == ['Mine']


def test_one_start_is_prepared_at_a_time(tmp_path, monkeypatch):
    import threading
    from raceplan.gui.jobs import Busy, Jobs
    jobs = Jobs(tmp_path, ROOT / 'scenarios')
    spec = jobs.validate({'scenarios': ['demo.yaml', 'validation_open.yaml'], 'planners': ['astar'], 'seeds': [0]})
    entered, release = threading.Event(), threading.Event()

    def slow_config(spec):  # Stands in for reading maps and hashing inputs.
        entered.set()
        release.wait(10)
        raise Busy('stopped for the test')
    monkeypatch.setattr(jobs, '_suite_config', slow_config)
    first = threading.Thread(target=lambda: pytest.raises(Busy, jobs._launch, spec))
    first.start()
    assert entered.wait(10)
    with pytest.raises(Busy, match='being prepared'):
        jobs._launch(spec)
    release.set()
    first.join(10)
    assert jobs.preparing is False


def _rc_case(case_id, scenario='s', seeds=(1, 2), noise=0.0, rows=(), versions=None):
    from hashlib import sha256
    digest = lambda text: sha256(text.encode()).hexdigest()  # noqa: E731
    manifest = {'scenario_sha256': digest(scenario), 'map_yaml_sha256': digest('m'), 'map_image_sha256': digest('i'),
                'experiment_revision': 2, 'simulation_seeds': list(seeds), 'noise': {'steering_std_rad': noise},
                'vehicle': {}, 'tracker': {}, 'simulation': {}, 'inflation_radius_m': 0.0, 'noise_model': 'n', 'collision_grid': 'g',
                'planners': {'astar': {'class': 'A', 'config': {}}, 'mine': {'class': 'M'}},
                'custom_planner_sources': {'mine': {'path': 'p.py', 'sha256': versions or 'a' * 64, 'class': 'Mine'}},
                'source_sha256': {'experiment.py': 'x', 'gui\\data.py': case_id}, 'python': '3.13', 'numpy': '2'}
    episodes = [{'planner': planner, 'simulation_seed': str(seed), 'failure_class': outcome,
                 'tracking_rmse_m': '' if outcome != 'reached' else str(rmse), 'completion_time_s': '' if outcome != 'reached' else '10',
                 'driving_min_sampled_clearance_m': str(rmse)} for planner, seed, outcome, rmse in rows]
    return {'id': case_id, 'manifest': manifest, 'episodes': episodes}


def test_two_runs_are_paired_by_saved_inputs_and_never_by_name():
    from raceplan.gui.run_compare import compare
    a = {'cases': [_rc_case('q0', 's', rows=[('mine', 1, 'driving_collision', 0), ('mine', 2, 'reached', 0.30),
                                             ('astar', 1, 'reached', 0.1), ('astar', 2, 'reached', 0.1)]),
                   _rc_case('old_only', 'gone', rows=[('mine', 1, 'reached', 0.1)]),
                   _rc_case('noisy', 'n', noise=0.0, rows=[('mine', 1, 'reached', 0.1)])]}
    b = {'cases': [_rc_case('renamed', 's', seeds=(2, 3), versions='b' * 64,
                            rows=[('mine', 2, 'reached', 0.20), ('mine', 3, 'reached', 0.2), ('astar', 2, 'reached', 0.1),
                                  ('astar', 3, 'reached', 0.1)]),
                   _rc_case('noisy', 'n', noise=0.01, rows=[('mine', 1, 'reached', 0.1)])]}
    result = compare(a, b)
    statuses = {tuple(case['case_a'] + case['case_b']): case['status'] for case in result['cases']}
    assert statuses == {('q0', 'renamed'): 'compared', ('old_only',): 'a_only', ('noisy', 'noisy'): 'condition_changed'}
    assert result['scope'] == 'overlap' and any('only one of the runs' in issue for issue in result['issues'])
    mine = next(item for item in result['planners'] if item['planner'] == 'mine')
    # Whole runs: A 3 reached of 4 (all its cases), B 3 of 3; paired: only seed 2 of the one compared case.
    assert mine['totals'] == {'a': {'recorded': 4, 'reached': 3}, 'b': {'recorded': 3, 'reached': 3}}
    assert mine['paired'] == 1 and mine['pairs']['both'] == 1
    assert mine['deltas']['rmse']['median'] == pytest.approx(-0.1) and mine['deltas']['rmse']['n'] == 1  # B - A
    assert not any('engine' in issue for issue in result['issues'])  # Only the explorer's own files differ.


def test_run_comparison_refuses_what_it_cannot_pair_honestly():
    from raceplan.gui.run_compare import compare
    twice = {'cases': [_rc_case('x', 's'), _rc_case('y', 's')]}
    assert compare(twice, {'cases': [_rc_case('z', 's')]})['cases'][0]['status'] == 'ambiguous'
    broken = {'cases': [_rc_case('q', 's', rows=[('mine', 1, 'reached', 0.1), ('mine', 1, 'reached', 0.2)])]}
    with pytest.raises(ValueError, match='appears twice'):
        compare(broken, broken)
    engine = _rc_case('q', 's')
    engine['manifest']['source_sha256'] = {'experiment.py': 'changed'}
    assert any('engine files differ' in issue for issue in compare({'cases': [_rc_case('q', 's')]}, {'cases': [engine]})['issues'])


def test_previous_run_and_watch_run_come_from_saved_files(two_case_suite, tmp_path, runner):
    import shutil
    from types import SimpleNamespace
    from raceplan.gui.jobs import _note_watch_run
    for name, finished in (('old', '2026-01-01T00:00:00Z'), ('mid', '2026-01-02T00:00:00Z'), ('new', '2026-01-03T00:00:00Z')):
        shutil.copytree(two_case_suite / 'two', tmp_path / 'gui-runs' / name)
        state = json.loads((tmp_path / 'gui-runs' / name / 'suite.json').read_text(encoding='utf-8'))
        state['finished_at_utc'] = finished
        (tmp_path / 'gui-runs' / name / 'suite.json').write_text(json.dumps(state), encoding='utf-8')
    _note_watch_run(SimpleNamespace(output=tmp_path / 'gui-runs/new', owner=SimpleNamespace(session='a1'), watch_run=3,
                                    trigger='change', record=None))
    explorer = Explorer(tmp_path)
    meta = {run['id']: run['meta'] for run in explorer.runs()}
    assert meta['gui-runs/new']['watch'] == {'watch_session': 'a1', 'watch_run': 3, 'trigger': 'change'}
    assert meta['gui-runs/old']['watch'] is None and meta['gui-runs/new']['cases_complete'] == 2
    answer = explorer.compare_runs('gui-runs/new')
    assert answer['suggested'] and answer['a']['id'] == 'gui-runs/mid'  # The latest earlier run of the same conditions.
    assert answer['result']['scope'] == 'full'
    assert all(item['totals']['a'] == item['totals']['b'] and item['pairs']['a_only'] == item['pairs']['b_only'] == 0
               for item in answer['result']['planners'])
    assert explorer.compare_runs('gui-runs/old')['a'] is None  # Nothing earlier: no made-up baseline.
    server = RunServer(tmp_path)
    try:
        assert server.request('GET', '/api/compare/runs?b=gui-runs/new&a=gui-runs/old')[0] == 200
        for bad, code in (('?b=gui-runs/new&a=gui-runs/new', 400), ('?b=gui-runs/new&x=1', 400), ('?a=gui-runs/old', 400),
                          ('?b=missing', 404)):
            assert server.request('GET', '/api/compare/runs' + bad)[0] == code, bad
    finally:
        server.close()


def test_run_comparison_needs_evidence_and_real_pairs():
    from raceplan.gui.run_compare import compare
    bare = _rc_case('q', 's', rows=[('mine', 1, 'reached', 0.1)])
    del bare['manifest']['scenario_sha256']  # An old or foreign manifest: which case is it?
    result = compare({'cases': [bare]}, {'cases': [dict(bare, manifest=dict(bare['manifest']))]})
    assert {case['status'] for case in result['cases']} == {'no_evidence'} and result['scope'] == 'none'
    mine = next(item for item in result['planners'] if item['planner'] == 'mine')
    assert mine['paired'] == 0 and mine['paired_change'] is None  # 1/1 vs 1/1 is not a change claimed over no pairs.
    moved = compare({'cases': [_rc_case('q0', 's')]}, {'cases': [_rc_case('q0', 'other')]})
    assert any('q0: its scenario or map files changed' in issue for issue in moved['issues'])
    runtime = _rc_case('q', 's')
    runtime['manifest']['numpy'] = '3'
    assert any('runtime' in issue for issue in compare({'cases': [_rc_case('q', 's')]}, {'cases': [runtime]})['issues'])


def test_watch_note_and_previous_run_are_not_trusted_blindly(two_case_suite, tmp_path):
    import shutil
    for name, finished in (('old', '2026-01-01T00:00:00+00:00'), ('undated', None)):
        shutil.copytree(two_case_suite / 'two', tmp_path / 'gui-runs' / name)
        state = json.loads((tmp_path / 'gui-runs' / name / 'suite.json').read_text(encoding='utf-8'))
        state['finished_at_utc'] = finished
        (tmp_path / 'gui-runs' / name / 'suite.json').write_text(json.dumps(state), encoding='utf-8')
    (tmp_path / 'gui-runs/.run-meta').mkdir()
    (tmp_path / 'gui-runs/.run-meta/old.json').write_text(json.dumps(  # Written for another state of the folder.
        {'schema_version': 1, 'run': 'old', 'state_sha256': '0' * 64, 'watch_session': 'a1', 'watch_run': 2,
         'trigger': 'change'}), encoding='utf-8')
    explorer = Explorer(tmp_path)
    assert {run['id']: run['meta']['watch'] for run in explorer.runs()}['gui-runs/old'] is None
    answer = explorer.compare_runs('gui-runs/undated')  # No finish time: it cannot know which run came before it.
    assert answer['a'] is None and answer['note'] == 'not_ready'
    assert explorer.compare_runs('gui-runs/undated', 'gui-runs/old')['result']['scope'] == 'full'


def test_repeated_seeds_and_repeated_cases_are_not_counted_twice():
    from raceplan.gui.run_compare import compare, run_meta
    twice = _rc_case('q', 's', seeds=(1, 1), rows=[('mine', 1, 'reached', 0.1)])
    assert compare({'cases': [twice]}, {'cases': [_rc_case('q', 's', rows=[('mine', 1, 'reached', 0.1)])]})['scope'] == 'none'
    same_inputs = [('x', _rc_case('x', 's')['manifest']), ('y', _rc_case('y', 's')['manifest'])]
    assert run_meta(same_inputs, 2, '2026-01-01T00:00:00+00:00', None)['fingerprint'] is None  # Never an automatic A.
    one = _rc_case('q', 's', rows=[('mine', 1, 'reached', 0.1), ('mine', 2, 'reached', 0.1), ('astar', 1, 'reached', 0.1)])
    other = _rc_case('q', 's', rows=[('mine', 1, 'reached', 0.1), ('mine', 2, 'reached', 0.1), ('astar', 1, 'reached', 0.1),
                                     ('astar', 2, 'reached', 0.1)])
    result = compare({'cases': [one]}, {'cases': [other]})
    assert next(p for p in result['planners'] if p['planner'] == 'astar')['pairs']['missing'] == 1
    assert result['scope'] == 'overlap'  # A slot only one run recorded keeps it from being a full comparison.
