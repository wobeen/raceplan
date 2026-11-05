import csv
import json
from pathlib import Path
import re
import shutil

from PIL import Image
import pytest
import yaml

from raceplan import analyze, experiment, report, suite, workflow
from raceplan.common import PlannerResult, PlannerStatus
from raceplan.planners import AStarPlanner

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/demo.yaml'


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_saved_legacy_batch_report_is_portable_and_does_not_plan_or_simulate(tmp_path, monkeypatch):
    source = tmp_path / 'legacy_batch'
    summary = source / 'comparison.csv'
    assert experiment.main([str(SCENARIO), '--output', str(summary), '--planners', 'astar',
                            '--simulation-seeds', '0', '1']) == 0
    rows = read_csv(summary)
    columns = [key for key in rows[0] if key not in {'runner_planning_time_ms', 'planning_error_type', 'planning_error_message', 'planning_error_truncated'}]
    with summary.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = source / 'comparison_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['source_sha256'] = {'historical.py': '0' * 64}
    manifest.pop('experiment_revision')
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    assert analyze.main([str(summary), '--baseline', 'astar', '--output-dir', str(source / 'analysis')]) == 0
    original_inputs = {str(path): report.sha256(path.read_bytes()).hexdigest() for path in source.rglob('*') if path.is_file()}
    monkeypatch.setattr(AStarPlanner, 'plan', lambda *args, **kwargs: pytest.fail('saved report must not plan'))
    monkeypatch.setattr('raceplan.simulator.run_episode', lambda *args, **kwargs: pytest.fail('saved report must not simulate'))
    output = tmp_path / 'report'
    assert report.main([str(source), '--output-dir', str(output)]) == 0
    page = (output / 'index.html').read_text(encoding='utf-8')
    provenance = json.loads((output / 'provenance.json').read_text())
    assert provenance['coverage'] == {'expected_episodes': 2, 'included_episodes': 2, 'missing_episodes': 0}
    assert 'n/a (n=0)' in page and 'Highest RMSE among reached' in page
    assert len(provenance['representatives']) == 1
    selected = provenance['representatives'][0]
    assert selected['simulation_seed'] == 0  # Equal zero-noise RMSE: lowest seed wins.
    samples = [r for r in read_csv(source / 'comparison_trajectory.csv') if r['episode_id'] == selected['episode_id']]
    assert selected['terminal_pose']['x_m'] == float(samples[-1]['x_m'])
    assert provenance['planning_calls'] == provenance['simulation_calls'] == 0
    assert provenance['historical_source_sha256']['batch'] == {'historical.py': '0' * 64}
    assert all(report.sha256(Path(path).read_bytes()).hexdigest() == digest for path, digest in original_inputs.items())
    copied = tmp_path / 'shared_copy'
    shutil.copytree(output, copied)
    for link in re.findall(r'(?:src|href)="([^"]+)"', page):
        assert not Path(link).is_absolute() and (copied / link).is_file()
    with pytest.raises(SystemExit):
        report.main([str(source), '--output-dir', str(output)])


def test_partial_suite_report_shows_missing_case_without_using_its_episodes(tmp_path, monkeypatch):
    config = {'version': 1, 'planners': ['astar'], 'simulation_seeds': [0, 1], 'cases': [
        {'id': 'failed', 'scenario': str(SCENARIO)},
        {'id': 'open', 'scenario': str(ROOT / 'scenarios/validation_open.yaml')}]}
    path = tmp_path / 'suite.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    original_report = workflow.custom_report.main

    def fail_first(command):
        if Path(command[0]).parent.name == 'failed':
            raise OSError('representative fixture report failed')
        return original_report(command)

    monkeypatch.setattr(workflow.custom_report, 'main', fail_first)
    source = tmp_path / 'suite'
    assert suite.main([str(path), '--output-dir', str(source)]) == 1
    output = tmp_path / 'partial_report'
    assert report.main([str(source), '--output-dir', str(output)]) == 0
    page = (output / 'index.html').read_text(encoding='utf-8')
    assert 'Cases complete: 1/2' in page and 'Missing episodes: 2' in page
    assert 'representative fixture report failed' in page
    provenance = json.loads((output / 'provenance.json').read_text())
    assert provenance['coverage']['included_episodes'] == 2
    assert all(row['case_id'] == 'open' for row in provenance['representatives'])
    assert len(provenance['representatives']) == 1


def test_all_planning_failures_show_no_driving_and_empty_success_denominators(tmp_path, monkeypatch):
    class NoPath:
        name = 'astar'

        def plan(self, *args, **kwargs):
            return PlannerResult(PlannerStatus.NO_PATH)

    monkeypatch.setitem(experiment.PLANNER_FACTORIES, 'astar', NoPath)
    source = tmp_path / 'all_failed'
    assert workflow.main([str(SCENARIO), '--output-dir', str(source), '--planners', 'astar',
                          '--custom-planner', f'{ROOT / "examples/error_planners.py"}:ExceptionPlanner']) == 0
    output = tmp_path / 'report'
    assert report.main([str(source), '--output-dir', str(output)]) == 0
    page = (output / 'index.html').read_text(encoding='utf-8')
    assert 'No driving: planning failed; no terminal pose.' in page
    assert 'n/a (n=0)' in page and '0/1' in page
    provenance = json.loads((output / 'provenance.json').read_text())
    assert len(provenance['representatives']) == 2
    assert all(row['category'] == 'Planning failure' and row['terminal_pose'] is None
               for row in provenance['representatives'])
    for path in (output / 'images').glob('*.png'):
        with Image.open(path) as image:
            assert image.size == (760, 540)
    pairs = source / 'analysis/paired.csv'
    rows = read_csv(pairs)
    assert rows[0]['both_reached'] == 'False'
    rows[0]['delta_completion_time_s'] = '999'
    write_csv(pairs, rows)
    refused = tmp_path / 'unqualified_delta'
    with pytest.raises(SystemExit):
        report.main([str(source), '--output-dir', str(refused)])
    assert not refused.exists()


def test_html_escapes_names_and_diagnostics_and_rejects_stale_inputs_and_map(tmp_path, monkeypatch):
    from dataclasses import replace
    from raceplan.defaults import baseline_vehicle

    monkeypatch.setattr(experiment, 'baseline_vehicle', lambda: replace(baseline_vehicle(), width=10.0))
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    shutil.copyfile(ROOT / 'maps/demo.pgm', inputs / 'map.pgm')
    metadata = yaml.safe_load((ROOT / 'maps/demo.yaml').read_text())
    metadata['image'] = 'map.pgm'
    (inputs / 'map.yaml').write_text(yaml.safe_dump(metadata), encoding='utf-8')
    scenario = yaml.safe_load(SCENARIO.read_text())
    scenario['map'] = 'map.yaml'
    scenario_path = inputs / 'scenario.yaml'
    scenario_path.write_text(yaml.safe_dump(scenario), encoding='utf-8')
    plugin = inputs / 'evil_name.py'
    plugin.write_text('''from raceplan.planners import AStarPlanner
class Escaped(AStarPlanner):
    name = "<img src=x onerror=alert(1)>"
    def plan(self, *args, **kwargs):
        raise ValueError("<script>alert('bad')</script>")
''', encoding='utf-8')
    source = tmp_path / 'saved'
    assert workflow.main([str(scenario_path), '--output-dir', str(source), '--planners', 'astar',
                          '--custom-planner', f'{plugin}:Escaped']) == 0
    output = tmp_path / 'escaped_report'
    assert report.main([str(source), '--output-dir', str(output)]) == 0
    page = (output / 'index.html').read_text(encoding='utf-8')
    assert '&lt;img src=x onerror=alert(1)&gt;' in page and '&lt;script&gt;' in page
    assert '<img src=x onerror' not in page and '<script>' not in page
    selections = json.loads((output / 'provenance.json').read_text())['representatives']
    assert {row['category'] for row in selections} == {'Driving failure', 'Planning failure'}
    driving = next(row for row in selections if row['category'] == 'Driving failure')
    assert driving['terminal_pose']['time_s'] == 0.0 and driving['outcome'] == 'initial_collision'
    episodes = source / 'analysis/episodes.csv'
    original_episodes = episodes.read_bytes()
    rows = read_csv(episodes)
    next(row for row in rows if row['failure_class'] == 'initial_collision')['failure_class'] = 'reached'
    write_csv(episodes, rows)
    false_reach = tmp_path / 'false_reach_report'
    with pytest.raises(SystemExit):
        report.main([str(source), '--output-dir', str(false_reach)])
    assert not false_reach.exists()
    episodes.write_bytes(original_episodes)
    summary = source / 'comparison.csv'
    original = summary.read_bytes()
    summary.write_bytes(original + b'\n')
    with pytest.raises(SystemExit):
        report.main([str(source), '--output-dir', str(tmp_path / 'stale_report')])
    assert not (tmp_path / 'stale_report').exists()
    summary.write_bytes(original)
    with (inputs / 'map.pgm').open('ab') as stream:
        stream.write(b'\n')
    with pytest.raises(SystemExit):
        report.main([str(source), '--output-dir', str(tmp_path / 'changed_map_report')])
    assert not (tmp_path / 'changed_map_report').exists()


def test_report_rejects_inconsistent_paired_rows(tmp_path, capsys):
    source = tmp_path / 'saved'
    assert workflow.main([str(SCENARIO), '--output-dir', str(source), '--planners', 'astar', 'dijkstra',
                          '--simulation-seeds', '0', '1']) == 0
    pairs = source / 'analysis/paired.csv'
    original = read_csv(pairs)
    assert len(original) == 2 and all(row['both_reached'] == 'True' for row in original)
    changes = {'baseline': 'dijkstra', 'planner_outcome': 'timeout', 'baseline_outcome': 'initial_collision',
               'both_reached': 'False', 'both_driven': 'False', 'simulation_seed': '1',
               'delta_tracking_rmse_m': '999', 'delta_completion_time_s': 'nan',
               'delta_driving_min_sampled_clearance_m': 'inf'}
    output = tmp_path / 'refused'
    for field, value in changes.items():
        write_csv(pairs, [original[0] | {field: value}, original[1]])
        with pytest.raises(SystemExit) as exc:
            report.main([str(source), '--output-dir', str(output)])
        assert exc.value.code == 2
        diagnostic = 'coverage mismatch' if field == 'simulation_seed' else field
        assert diagnostic in capsys.readouterr().err
        assert not output.exists()
