import csv
import json
from pathlib import Path

import pytest
import yaml

from raceplan import suite

ROOT = Path(__file__).resolve().parents[1]


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def configuration():
    return {'version': 1, 'cases': [
        {'id': 'demo', 'scenario': str(ROOT / 'scenarios/demo.yaml')},
        {'id': 'open', 'scenario': str(ROOT / 'scenarios/validation_open.yaml')}],
        'planners': ['astar'], 'simulation_seeds': [0, 1]}


def save(path, value):
    path.write_text(yaml.safe_dump(value), encoding='utf-8')
    return path


def test_suite_e2e_relative_paths_keys_errors_and_plan_deduplication(tmp_path, monkeypatch):
    config_folder = tmp_path / 'config'
    scripts = tmp_path / 'scripts'
    elsewhere = tmp_path / 'elsewhere'
    for folder in (config_folder, scripts, elsewhere):
        folder.mkdir()
    counter = tmp_path / 'imports.txt'
    plugin = scripts / '--plugin.py'
    plugin.write_text(f'''from pathlib import Path
from raceplan.planners import AStarPlanner
counter = Path({str(counter)!r})
counter.write_text(counter.read_text() + "x" if counter.exists() else "x")
class Good(AStarPlanner):
    name = "--mine"
''', encoding='utf-8')
    data = configuration()
    data.update(custom_planners=['../scripts/--plugin.py:Good',
                                 f'{ROOT / "examples/error_planners.py"}:ExceptionPlanner'],
                baseline='--mine', report_seed=1, inflation_radius_m=.1,
                spacing_m=.2, noise={'steering_std_rad': .01})
    path = save(config_folder / 'suite.yaml', data)
    monkeypatch.chdir(elsewhere)
    output = tmp_path / 'run'
    assert suite.main([str(path), '--output-dir', str(output)]) == 0
    assert counter.read_text() == 'xx'  # Once per case, with no preflight import.
    resolved = json.loads((output / 'resolved_config.json').read_text())
    assert resolved['settings']['custom_planners'][0] == f'{plugin.resolve()}:Good'
    state = json.loads((output / 'suite.json').read_text())
    assert state['status'] == 'complete'
    assert state['coverage'] == {'expected_cases': 2, 'completed_cases': 2, 'failed_cases': 0,
                                 'not_run_cases': 0, 'expected_episode_count': 12,
                                 'included_episode_count': 12, 'missing_episode_count': 0}
    episodes = read_csv(output / 'episodes.csv')
    plans, pairs = read_csv(output / 'planning.csv'), read_csv(output / 'paired.csv')
    assert len(episodes) == len({r['episode_key'] for r in episodes}) == 12
    assert len(plans) == len({r['plan_key'] for r in plans}) == 6
    assert len(pairs) == len({r['pair_key'] for r in pairs}) == 8
    errors = [row for row in episodes if row['planner'] == 'example_exception']
    assert len(errors) == 4 and all(r['planning_status'] == 'planning_error' for r in errors)
    assert all(r['baseline'] == '--mine' for r in pairs)
    assert all(r['both_reached'] == 'False' and r['delta_tracking_rmse_m'] == ''
               for r in pairs if r['planner'] == 'example_exception')
    summaries = {r['planner']: r for r in read_csv(output / 'summary.csv')}
    assert summaries['astar']['reached'] == summaries['--mine']['reached'] == '4'
    assert summaries['example_exception']['planning_errors'] == '4'
    assert summaries['example_exception']['success_median_tracking_rmse_m'] == ''
    assert all(r['planning_calls'] == r['runner_planning_time_ms_samples'] == '2' for r in summaries.values())
    assert len(read_csv(output / 'case_summary.csv')) == 6
    assert all((output / 'cases' / case / 'comparison.png').is_file() for case in ('demo', 'open'))
    provenance = json.loads((output / 'provenance.json').read_text())
    assert provenance['resolved_config_sha256'] == suite._hash(output / 'resolved_config.json')
    assert all(suite._hash(Path(name)) == value for name, value in provenance['input_sha256'].items())


def test_suite_rejects_strict_config_errors_and_existing_output_before_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(suite.workflow, 'main', lambda _: pytest.fail('invalid configuration must not execute'))
    malformed = []
    for patch in ({'unknown': 1}, {'version': True}, {'simulation_seeds': [True]},
                  {'simulation_seeds': [1, 1]}, {'noise': {'typo': .1}},
                  {'noise': {'steering_std_rad': float('inf')}}, {'planners': []},
                  {'report_seed': 3}, {'custom_planners': ['missing.py:Class']}):
        malformed.append(configuration() | patch)
    for identity in ('../escape', 'CON', 'bad.name'):
        value = configuration()
        value['cases'][0]['id'] = identity
        malformed.append(value)
    duplicate = configuration()
    duplicate['cases'][1]['id'] = 'DEMO'
    malformed.append(duplicate)
    for index, value in enumerate(malformed):
        path = save(tmp_path / f'bad_{index}.yaml', value)
        output = tmp_path / f'bad_output_{index}'
        with pytest.raises(SystemExit) as failure:
            suite.main([str(path), '--output-dir', str(output)])
        assert failure.value.code == 2 and not output.exists()
    duplicate_keys = tmp_path / 'duplicate.yaml'
    duplicate_keys.write_text('version: 1\nversion: 1\ncases: []\n', encoding='utf-8')
    with pytest.raises(SystemExit):
        suite.main([str(duplicate_keys), '--output-dir', str(tmp_path / 'duplicate_output')])
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'suite.json'
    sentinel.write_text('preserve', encoding='utf-8')
    with pytest.raises(SystemExit):
        suite.main([str(save(tmp_path / 'valid.yaml', configuration())), '--output-dir', str(existing)])
    assert sentinel.read_text() == 'preserve'


def test_failed_case_is_preserved_and_later_case_runs_with_missing_coverage(tmp_path, monkeypatch):
    data = configuration()
    data['cases'][0]['id'] = 'failed'
    path = save(tmp_path / 'suite.yaml', data)
    original_report = suite.workflow.custom_report.main

    def selective_failure(command):
        if Path(command[0]).parent.name == 'failed':
            Path(command[2]).write_bytes(b'partial PNG')
            raise OSError('report unavailable')
        return original_report(command)

    monkeypatch.setattr(suite.workflow.custom_report, 'main', selective_failure)
    output = tmp_path / 'partial'
    assert suite.main([str(path), '--output-dir', str(output)]) == 1
    state = json.loads((output / 'suite.json').read_text())
    assert state['status'] == 'partial'
    assert state['coverage'] == {'expected_cases': 2, 'completed_cases': 1, 'failed_cases': 1,
                                 'not_run_cases': 0, 'expected_episode_count': 4,
                                 'included_episode_count': 2, 'missing_episode_count': 2}
    coverage = {r['case_id']: r for r in read_csv(output / 'coverage.csv')}
    assert coverage['failed']['raw_episode_count'] == '2' and coverage['failed']['included_episode_count'] == '0'
    assert coverage['failed']['failed_phase'] == 'report'
    assert len(read_csv(output / 'episodes.csv')) == 2
    summary = read_csv(output / 'summary.csv')[0]
    assert summary['coverage_complete'] == 'False' and summary['missing_episode_count'] == '2'
    assert summary['episodes_recorded'] == '2' and summary['reach_rate_observed'] == '1.0'
    assert (output / 'cases/failed/comparison.png').read_bytes() == b'partial PNG'
    assert (output / 'cases/open/comparison.png').is_file()

    class BadString(Exception):
        def __str__(self):
            raise RuntimeError('cannot stringify')

    assert suite._error(BadString())['message'] == '<exception message unavailable>'


def test_control_exceptions_stop_suite_and_mark_remaining_cases_not_run(tmp_path):
    plugin = tmp_path / 'stop.py'
    for index, (expression, exit_code) in enumerate((('SystemExit(7)', 7), ('KeyboardInterrupt()', 130),
                                                    ('CustomExit(7)', 7), ('CustomInterrupt()', 130))):
        plugin.write_text(f'''from raceplan.planners import AStarPlanner
class CustomExit(SystemExit):
    pass
class CustomInterrupt(KeyboardInterrupt):
    pass
class Stops(AStarPlanner):
    name = "stops"
    def plan(self, *args, **kwargs):
        raise {expression}
''', encoding='utf-8')
        data = configuration()
        data.update(custom_planners=[f'{plugin}:Stops'], simulation_seeds=[0])
        path = save(tmp_path / f'stop_{index}.yaml', data)
        output = tmp_path / f'interrupted_{index}'
        assert suite.main([str(path), '--output-dir', str(output)]) == exit_code
        state = json.loads((output / 'suite.json').read_text())
        assert state['status'] == 'interrupted'
        assert state['coverage']['failed_cases'] == state['coverage']['not_run_cases'] == 1
        assert state['coverage']['missing_episode_count'] == 4
        assert state['cases']['demo']['error']['control_exception'] is True
        assert read_csv(output / 'episodes.csv') == []
        assert not (output / 'cases/open').exists()
