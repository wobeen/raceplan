import csv
import json
from pathlib import Path

from PIL import Image
import pytest
import yaml

from raceplan import workflow

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/demo.yaml'


def state(folder):
    return json.loads((folder / 'workflow.json').read_text(encoding='utf-8'))


def test_workflow_runs_custom_comparison_analysis_and_selected_seed_report_once(tmp_path):
    counter = tmp_path / 'imports.txt'
    plugin = tmp_path / 'plugin.py'
    plugin.write_text(f'''from pathlib import Path
from raceplan.planners import AStarPlanner
counter = Path({str(counter)!r})
counter.write_text(counter.read_text() + "x" if counter.exists() else "x")
class UserPlanner(AStarPlanner):
    name = "user_planner"
''', encoding='utf-8')
    output = tmp_path / 'run'
    assert workflow.main([str(SCENARIO), '--output-dir', str(output), '--planners', 'astar',
                          '--custom-planner', f'{plugin}:UserPlanner', '--baseline', 'user_planner',
                          '--simulation-seeds', '5', '7', '--report-seed', '7', '--spacing', '0.2',
                          '--inflation-radius', '0.15', '--initial-position-std-m', '0.01',
                          '--initial-yaw-std-rad', '0.01', '--initial-speed-std-mps', '0.01',
                          '--steering-std-rad', '0.005', '--speed-measurement-std-mps', '0.02']) == 0
    assert counter.read_text() == 'x'
    status = state(output)
    assert status['status'] == 'complete' and status['failed_phase'] is None
    assert status['current_phase'] is None and status['report_seed'] == 7
    assert all(phase['status'] == 'complete' for phase in status['phases'].values())
    manifest = json.loads((output / 'comparison_manifest.json').read_text(encoding='utf-8'))
    assert manifest['simulation_seeds'] == [5, 7]
    assert manifest['inflation_radius_m'] == .15
    assert manifest['noise'] == {'initial_position_std_m': .01, 'initial_yaw_std_rad': .01,
                                 'initial_speed_std_mps': .01, 'steering_std_rad': .005,
                                 'speed_measurement_std_mps': .02}
    with (output / 'comparison.csv').open(newline='', encoding='utf-8') as stream:
        assert {(r['planner'], r['simulation_seed']) for r in csv.DictReader(stream)} == {
            ('astar', '5'), ('astar', '7'), ('user_planner', '5'), ('user_planner', '7')}
    analysis = json.loads((output / 'analysis/analysis.json').read_text(encoding='utf-8'))
    assert analysis['baseline'] == 'user_planner' and analysis['requested_spacing_m'] == .2
    with Image.open(output / 'comparison.png') as rendered:
        assert rendered.size == (1200, 865)
    assert not list(output.glob('.workflow-*.tmp'))


def test_preflight_rejects_bad_options_and_existing_output_without_running(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow.experiment, 'main', lambda _: pytest.fail('preflight must not start an experiment'))
    options = [
        ['--baseline', 'absent'], ['--simulation-seeds', '1', '1'],
        ['--simulation-seeds', '1', '--report-seed', '2'], ['--inflation-radius', 'nan'],
        ['--steering-std-rad', '-0.1'], ['--spacing', '0'],
        ['--output', str(tmp_path / 'reserved.csv')], ['--out', str(tmp_path / 'abbreviated')],
    ]
    for index, extra in enumerate(options):
        output = tmp_path / f'rejected_{index}'
        with pytest.raises(SystemExit) as failure:
            workflow.main([str(SCENARIO), '--output-dir', str(output), *extra])
        assert failure.value.code == 2 and not output.exists()
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'workflow.json'
    sentinel.write_text('existing user data', encoding='utf-8')
    with pytest.raises(SystemExit):
        workflow.main([str(SCENARIO), '--output-dir', str(existing)])
    assert sentinel.read_text(encoding='utf-8') == 'existing user data'


def test_dash_prefixed_scenario_plugin_and_custom_baseline_survive_forwarding(tmp_path, monkeypatch):
    scenario_data = yaml.safe_load(SCENARIO.read_text(encoding='utf-8'))
    scenario_data['map'] = str(ROOT / 'maps/demo.yaml')
    (tmp_path / '-demo.yaml').write_text(yaml.safe_dump(scenario_data), encoding='utf-8')
    (tmp_path / '--foo.py').write_text('''from raceplan.planners import AStarPlanner
class UserPlanner(AStarPlanner):
    name = "--mine"
''', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    output = tmp_path / 'dash_names'
    assert workflow.main(['--output-dir', str(output), '--planners', 'astar',
                          '--custom-planner=--foo.py:UserPlanner', '--baseline=--mine',
                          '--', '-demo.yaml']) == 0
    assert state(output)['status'] == 'complete'
    analysis = json.loads((output / 'analysis/analysis.json').read_text(encoding='utf-8'))
    assert analysis['baseline'] == '--mine'
    manifest = json.loads((output / 'comparison_manifest.json').read_text(encoding='utf-8'))
    assert set(manifest['planners']) == {'astar', '--mine'}
    assert manifest['scenario_file'] == str(tmp_path / '-demo.yaml')


def test_experiment_failure_preserves_partial_outputs_and_skips_later_phases(tmp_path):
    plugin = tmp_path / 'broken.py'
    plugin.write_text('''from raceplan.planners import AStarPlanner
class Broken(AStarPlanner):
    name = "broken"
    def plan(self, *args, **kwargs):
        raise RuntimeError("candidate failed during planning")
''', encoding='utf-8')
    output = tmp_path / 'partial'
    assert workflow.main([str(SCENARIO), '--output-dir', str(output), '--planners', 'astar',
                          '--custom-planner', f'{plugin}:Broken']) == 1
    status = state(output)
    assert status['status'] == 'failed' and status['failed_phase'] == 'experiment'
    assert status['phases']['analysis']['status'] == status['phases']['report']['status'] == 'pending'
    assert status['error']['type'] == 'RuntimeError'
    assert 'candidate failed' in status['error']['message']
    manifest = json.loads((output / 'comparison_manifest.json').read_text(encoding='utf-8'))
    assert manifest['status'] == 'running'
    with (output / 'comparison.csv').open(newline='', encoding='utf-8') as stream:
        assert [r['planner'] for r in csv.DictReader(stream)] == ['astar']
    assert not (output / 'analysis').exists() and not (output / 'comparison.png').exists()


def test_absent_custom_baseline_fails_after_manifest_without_importing_twice(tmp_path):
    output = tmp_path / 'custom_baseline'
    assert workflow.main([str(SCENARIO), '--output-dir', str(output), '--planners', 'astar',
                          '--custom-planner', f'{ROOT / "examples/my_planner.py"}:MyPlanner',
                          '--baseline', 'absent_custom']) == 1
    status = state(output)
    assert status['failed_phase'] == 'analysis'
    assert status['phases']['experiment']['status'] == 'complete'
    assert status['phases']['report']['status'] == 'pending'
    assert 'absent from the completed comparison' in status['error']['message']
    assert not (output / 'analysis').exists() and (output / 'comparison_paths.csv').exists()


def test_report_failure_keeps_analysis_and_partial_png(tmp_path, monkeypatch):
    def broken_report(command):
        Path(command[2]).write_bytes(b'partial PNG')
        raise OSError('render interrupted')

    monkeypatch.setattr(workflow.custom_report, 'main', broken_report)
    output = tmp_path / 'report_failure'
    assert workflow.main([str(SCENARIO), '--output-dir', str(output), '--planners', 'astar']) == 1
    status = state(output)
    assert status['failed_phase'] == 'report'
    assert status['phases']['experiment']['status'] == status['phases']['analysis']['status'] == 'complete'
    assert (output / 'analysis/planners.csv').exists()
    assert (output / 'comparison.png').read_bytes() == b'partial PNG'
