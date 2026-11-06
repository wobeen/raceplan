import csv
import http.client
import json
from pathlib import Path
from threading import Thread

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
    assert client('/', method='POST')[0].status == 501


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
