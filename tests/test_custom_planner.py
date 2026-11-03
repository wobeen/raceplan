import csv
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from raceplan.custom_report import main as report_main, render_report
from raceplan.experiment import main
from raceplan.planners.custom import load_custom_planner


def test_custom_planner_runs_paired_and_records_provenance(tmp_path):
    root = Path(__file__).resolve().parents[1]
    plugin = tmp_path / 'plugin.py'
    plugin.write_text('''from raceplan.planners.base import Planner
from raceplan.planners import AStarPlanner
from raceplan.common import PlannerResult, PlannerStatus
class UserPlanner(Planner):
    name = "user_planner"
    config = {"example": True}
    def plan(self, grid, start, goal, *, timeout_s=None):
        result = AStarPlanner().plan(grid, start, goal, timeout_s=timeout_s)
        grid.occupied.setflags(write=True)
        grid.occupied[:] = True
        return result
class NoPathPlanner(Planner):
    name = "no_path"
    def plan(self, grid, start, goal, *, timeout_s=None):
        return PlannerResult(PlannerStatus.NO_PATH)
''')
    output = tmp_path / 'comparison.csv'
    assert main([str(root/'scenarios/demo.yaml'), '--output', str(output), '--planners', 'astar',
                 '--custom-planner', f'{plugin}:UserPlanner',
                 '--custom-planner', f'{plugin}:NoPathPlanner',
                 '--initial-position-std-m', '0.01', '--steering-std-rad', '0.01',
                 '--simulation-seeds', '0', '1']) == 0
    with output.open(encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    assert {(r['planner'], r['simulation_seed']) for r in rows} == {
        ('astar', '0'), ('astar', '1'), ('user_planner', '0'), ('user_planner', '1'),
        ('no_path', '0'), ('no_path', '1')}
    assert all(r['planning_status'] == 'success' for r in rows[:4])
    for baseline, custom in zip(rows[:2], rows[2:4]):
        assert {k: v for k, v in baseline.items() if k not in {'episode_id', 'plan_id', 'planner', 'planning_time_ms', 'runner_planning_time_ms'}} == {
            k: v for k, v in custom.items() if k not in {'episode_id', 'plan_id', 'planner', 'planning_time_ms', 'runner_planning_time_ms'}}
    assert all(r['planning_status'] == 'no_path' and r['simulation_status'] == 'not_run' for r in rows[4:])
    manifest = json.loads(output.with_name('comparison_manifest.json').read_text())
    assert manifest['custom_planner_sources']['user_planner']['sha256'] == hashlib.sha256(plugin.read_bytes()).hexdigest()
    assert manifest['planners']['user_planner']['config'] == {"example": True}
    assert output.with_name('comparison_trajectory.csv').exists()
    assert output.with_name('comparison_paths.csv').exists()
    with output.with_name('comparison_trajectory.csv').open(encoding='utf-8') as stream:
        samples = list(csv.DictReader(stream))
    for seed in ('0', '1'):
        baseline = [{k: v for k, v in s.items() if k != 'episode_id'} for s in samples if s['episode_id'] == f'astar:{seed}']
        custom = [{k: v for k, v in s.items() if k != 'episode_id'} for s in samples if s['episode_id'] == f'user_planner:{seed}']
        assert baseline == custom
    # The saved query is sufficient: rendering does not reload the scenario file.
    manifest['scenario_file'] = str(tmp_path / 'removed_scenario.yaml')
    output.with_name('comparison_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    image = tmp_path / 'report.png'
    assert report_main([str(output), '--output', str(image), '--seed', '1']) == 0
    with Image.open(image) as rendered:
        assert rendered.size == (1200, 1235)
    before = image.read_bytes()
    with pytest.raises(ValueError, match='already exists'):
        render_report(output, image)
    assert image.read_bytes() == before
    with pytest.raises(ValueError, match='absent'):
        render_report(output, tmp_path / 'missing_seed.png', 99)
    manifest['map_yaml_sha256'] = 'changed'
    output.with_name('comparison_manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError, match='map YAML changed'):
        render_report(output, tmp_path / 'changed_map.png')


def test_custom_planner_rejects_duplicate_names_before_creating_results(tmp_path):
    root = Path(__file__).resolve().parents[1]
    plugin = tmp_path / 'plugin.py'
    plugin.write_text('from raceplan.planners import AStarPlanner\nclass UserPlanner(AStarPlanner):\n    pass\n')
    output = tmp_path / 'comparison.csv'
    with pytest.raises(SystemExit):
        main([str(root/'scenarios/demo.yaml'), '--output', str(output), '--planners', 'astar',
              '--custom-planner', f'{plugin}:UserPlanner'])
    assert not output.exists()


def test_loader_uses_recorded_source_and_reports_plugin_errors(tmp_path):
    plugin = tmp_path / 'plugin.py'
    template = 'from raceplan.planners import AStarPlanner\nclass UserPlanner(AStarPlanner):\n    name = "{}"\n'
    plugin.write_text(template.format('first'))
    first, first_source = load_custom_planner(f'{plugin}:UserPlanner')
    plugin.write_text(template.format('other'))
    other, other_source = load_custom_planner(f'{plugin}:UserPlanner')
    assert first.name == 'first' and other.name == 'other'
    assert first_source['sha256'] != other_source['sha256']
    plugin.write_text('raise RuntimeError("plugin import failed")\n')
    with pytest.raises(ValueError, match='plugin import failed'):
        load_custom_planner(f'{plugin}:UserPlanner')


def test_config_dataclass_is_preserved_and_invalid_values_create_no_artifacts(tmp_path, capsys, monkeypatch):
    import raceplan.experiment as experiment
    from raceplan.common import PlannerResult, PlannerStatus

    class FailedBaseline:
        name = 'astar'

        def plan(self, *args, **kwargs):
            return PlannerResult(PlannerStatus.NO_PATH)

    monkeypatch.setitem(experiment.PLANNER_FACTORIES, 'astar', FailedBaseline)
    plugin = tmp_path / 'settings.py'
    source = '''from dataclasses import dataclass, field
from collections import UserDict
from pathlib import Path
import numpy as np
from raceplan.planners.base import Planner
from raceplan.common import PlannerResult, PlannerStatus
@dataclass
class Settings:
    weights: tuple = (1.0, 2.0)
    options: object = field(default_factory=lambda: UserDict({"enabled": True, "label": None}))
    resource: object = field(default_factory=lambda: RESOURCE)
class ConfigPlanner(Planner):
    name = "configured"
    config = Settings()
    def plan(self, grid, start, goal, *, timeout_s=None):
        return PlannerResult(PlannerStatus.NO_PATH)
'''
    scenario = Path(__file__).resolve().parents[1] / 'scenarios/demo.yaml'
    plugin.write_text(source.replace('RESOURCE', 'None'))
    output = tmp_path / 'valid' / 'comparison.csv'
    arguments = [str(scenario), '--planners', 'astar', '--custom-planner', f'{plugin}:ConfigPlanner']
    assert main(arguments + ['--output', str(output)]) == 0
    manifest = json.loads(output.with_name('comparison_manifest.json').read_text())
    assert manifest['planners']['configured']['config'] == {
        'weights': [1.0, 2.0], 'options': {'enabled': True, 'label': None}, 'resource': None}
    # Both common non-JSON scientific settings must fail before creating even a directory.
    for index, expression in enumerate(('Path("weights.bin")', 'np.array([1, 2])')):
        plugin.write_text(source.replace('RESOURCE', expression))
        rejected = tmp_path / f'rejected_{index}' / 'comparison.csv'
        with pytest.raises(SystemExit) as failure:
            main(arguments + ['--output', str(rejected)])
        assert failure.value.code == 2
        assert not rejected.parent.exists()
        error = capsys.readouterr().err
        assert "planner 'configured' config.resource" in error
        assert 'unsupported configuration type' in error
