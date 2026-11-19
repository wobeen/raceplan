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
