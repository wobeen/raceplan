import csv
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import pytest

from raceplan import analyze, custom_report, experiment, workflow
from raceplan.common import OccupancyGrid, Path as PlannedPath, PlannerResult, PlannerStatus, Pose2D
from raceplan.planners import execution

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / 'scenarios/demo.yaml'
GRID = OccupancyGrid(np.zeros((2, 2), dtype=bool), 1.0)
START, GOAL = Pose2D(.5, .5), Pose2D(1.5, 1.5)


def read_csv(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def test_runner_times_only_one_plan_call_and_snapshots_valid_result(monkeypatch):
    timestamps = iter((10.0, 10.125))
    monkeypatch.setattr(execution, 'perf_counter', lambda: next(timestamps))
    points = [Pose2D(-50, 100, 0)]  # Data validity does not certify map/vehicle safety.
    calls = []

    class ReturnsPath:
        def plan(self, *args, **kwargs):
            calls.append(1)
            return PlannerResult(PlannerStatus.SUCCESS, PlannedPath(points, 0), planning_time_s=.002)

    outcome = execution.plan_once(ReturnsPath(), GRID, START, GOAL, timeout_s=1, is_custom=True)
    assert calls == [1] and outcome.runner_planning_time_ms == 125.0
    assert outcome.result.planning_time_s == .002 and outcome.reported_time_available
    points.clear()
    assert outcome.result.path.poses == (Pose2D(-50, 100, 0),)
    assert not outcome.error_type


def test_custom_result_contract_errors_are_explicit_and_contained():
    corrupted_pose = Pose2D(0, 0)
    object.__setattr__(corrupted_pose, 'x', float('nan'))
    missing_path = PlannerResult(PlannerStatus.SUCCESS, PlannedPath((START,), 0))
    object.__setattr__(missing_path, 'path', None)
    failure_with_path = PlannerResult(PlannerStatus.NO_PATH)
    object.__setattr__(failure_with_path, 'path', PlannedPath((START,), 0))
    invalid_results = [
        ({'status': 'success'}, 'must return'), (PlannerResult('success'), 'status'),
        (PlannerResult(PlannerStatus.SUCCESS, PlannedPath((object(),), 0)), 'Pose2D'),
        (PlannerResult(PlannerStatus.SUCCESS, PlannedPath((corrupted_pose,), 0)), 'finite'),
        (missing_path, 'successful result.path'), (failure_with_path, 'cannot contain a path'),
        (PlannerResult(PlannerStatus.NO_PATH, expanded_nodes=.5), 'integer'),
        (PlannerResult(PlannerStatus.NO_PATH, planning_time_s=1e307), 'milliseconds'),
    ]
    for returned, message in invalid_results:
        class Invalid:
            def plan(self, *args, **kwargs):
                return returned

        outcome = execution.plan_once(Invalid(), GRID, START, GOAL, timeout_s=1, is_custom=True)
        assert outcome.result.status is PlannerStatus.ERROR and outcome.result.path is None
        assert message in outcome.error_message and outcome.error_type in {'TypeError', 'ValueError'}
        assert outcome.runner_planning_time_ms >= 0 and not outcome.reported_time_available


def test_control_exceptions_and_builtin_errors_propagate():
    class Raises:
        def __init__(self, failure):
            self.failure = failure

        def plan(self, *args, **kwargs):
            raise self.failure

    for error in (KeyboardInterrupt(), SystemExit(23)):
        with pytest.raises(type(error)):
            execution.plan_once(Raises(error), GRID, START, GOAL, timeout_s=1, is_custom=True)
    with pytest.raises(RuntimeError, match='builtin bug'):
        execution.plan_once(Raises(RuntimeError('builtin bug')), GRID, START, GOAL,
                            timeout_s=1, is_custom=False)

    class InvalidBuiltin:
        def plan(self, *args, **kwargs):
            return None

    with pytest.raises(TypeError, match='must return'):
        execution.plan_once(InvalidBuiltin(), GRID, START, GOAL, timeout_s=1, is_custom=False)


def test_workflow_continues_after_custom_exceptions_and_bad_result_with_all_seed_errors(tmp_path, monkeypatch):
    plugin = tmp_path / 'candidates.py'
    plugin.write_text('''from raceplan.planners import AStarPlanner
class Raises(AStarPlanner):
    name = "raises"
    def plan(self, grid, *args, **kwargs):
        grid.occupied.setflags(write=True)
        grid.occupied[:] = True
        raise RuntimeError("candidate failed")
class Invalid(AStarPlanner):
    name = "invalid"
    def plan(self, *args, **kwargs):
        return None
class Good(AStarPlanner):
    name = "good"
''', encoding='utf-8')
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture_text)
    output = tmp_path / 'mixed'
    args = [str(SCENARIO), '--output-dir', str(output), '--planners', 'astar', '--simulation-seeds', '0', '1']
    for classname in ('Raises', 'Invalid', 'Good'):
        args += ['--custom-planner', f'{plugin}:{classname}']
    assert workflow.main(args) == 0
    assert json.loads((output / 'workflow.json').read_text())['status'] == 'complete'
    rows = read_csv(output / 'comparison.csv')
    assert len(rows) == 8
    errors = [row for row in rows if row['planner'] in {'raises', 'invalid'}]
    assert all(row['planning_status'] == 'planning_error' and row['simulation_status'] == 'not_run' for row in errors)
    assert {row['planning_error_type'] for row in errors} == {'RuntimeError', 'TypeError'}
    assert all(row['planning_error_message'] and row['planning_time_ms'] == row['expanded_nodes'] == '' for row in errors)
    assert all(row['reached'] == row['collision'] == 'False' for row in errors)
    for planner in {'astar', 'raises', 'invalid', 'good'}:
        group = [r for r in rows if r['planner'] == planner]
        assert len({r['runner_planning_time_ms'] for r in group}) == 1
        assert float(group[0]['runner_planning_time_ms']) >= 0
    assert all(row['planning_status'] == 'success' for row in rows if row['planner'] in {'astar', 'good'})
    assert all(row['simulation_status'] == 'reached' for row in rows if row['planner'] in {'astar', 'good'})
    assert {r['plan_id'] for r in read_csv(output / 'comparison_paths.csv')} == {'astar', 'good'}
    pairs = read_csv(output / 'analysis/paired.csv')
    assert all(r['both_reached'] == 'False' and not r['delta_tracking_rmse_m']
               for r in pairs if r['planner'] in {'raises', 'invalid'})
    aggregates = read_csv(output / 'analysis/planners.csv')
    assert all(r['planning_calls'] == '1' for r in aggregates)
    assert all(r['planning_errors'] == r['planning_failures'] == '2'
               for r in aggregates if r['planner'] in {'raises', 'invalid'})
    assert any(text.startswith('Error: RuntimeError | candidate failed') for text in drawn)
    assert any('runner wall' in text for text in drawn)
    with Image.open(output / 'comparison.png') as rendered:
        assert rendered.size == (1200, 1605)


def test_all_planning_failures_still_produce_analysis_and_png(tmp_path, monkeypatch):
    class NoPath:
        name = 'astar'

        def plan(self, *args, **kwargs):
            return PlannerResult(PlannerStatus.NO_PATH)

    monkeypatch.setitem(experiment.PLANNER_FACTORIES, 'astar', NoPath)
    output = tmp_path / 'all_failed'
    assert workflow.main([str(SCENARIO), '--output-dir', str(output), '--planners', 'astar',
                          '--custom-planner', f'{ROOT / "examples/error_planners.py"}:ExceptionPlanner',
                          '--simulation-seeds', '0', '1']) == 0
    aggregates = read_csv(output / 'analysis/planners.csv')
    assert all(r['reached'] == r['driven_episodes'] == '0' for r in aggregates)
    assert all(r['planning_failures'] == '2' for r in aggregates)
    assert all(not r['all_driven_min_clearance_m_min'] for r in aggregates)
    assert all(r['both_driven'] == 'False' for r in read_csv(output / 'analysis/paired.csv'))
    assert (output / 'comparison.png').is_file()


def test_workflow_bounds_diagnostics_renders_single_lines_and_rejects_infinite_ms(tmp_path, monkeypatch):
    plugin = tmp_path / 'diagnostics.py'
    plugin.write_text('''from raceplan.planners import AStarPlanner
from raceplan.common import PlannerResult, PlannerStatus
class Multiline(AStarPlanner):
    name = "multiline"
    def plan(self, *args, **kwargs):
        raise RuntimeError("line one\\nline two\\tcontrol\\x00end")
class Long(AStarPlanner):
    name = "long"
    def plan(self, *args, **kwargs):
        raise type("E" * 140000, (RuntimeError,), {})("M" * 140000)
class HugeTime(AStarPlanner):
    name = "huge_time"
    def plan(self, *args, **kwargs):
        return PlannerResult(PlannerStatus.NO_PATH, planning_time_s=1e307)
class Good(AStarPlanner):
    name = "good"
''', encoding='utf-8')
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture_text)
    output = tmp_path / 'diagnostics'
    args = [str(SCENARIO), '--output-dir', str(output), '--planners', 'astar']
    for classname in ('Multiline', 'Long', 'HugeTime', 'Good'):
        args += ['--custom-planner', f'{plugin}:{classname}']
    assert workflow.main(args) == 0
    rows = {r['planner']: r for r in read_csv(output / 'comparison.csv')}
    assert rows['multiline']['planning_error_message'] == 'line one\nline two\tcontrol\x00end'
    assert rows['multiline']['planning_error_truncated'] == 'False'
    assert len(rows['long']['planning_error_type']) <= 128
    assert len(rows['long']['planning_error_message']) <= 4096
    assert rows['long']['planning_error_message'].endswith('... [truncated]')
    assert rows['long']['planning_error_truncated'] == 'True'
    assert 'finite milliseconds' in rows['huge_time']['planning_error_message']
    assert rows['huge_time']['planning_time_ms'] == ''
    assert all(np.isfinite(float(row['runner_planning_time_ms'])) for row in rows.values())
    assert rows['good']['simulation_status'] == 'reached'
    assert all(not any(char in text for char in ('\n', '\r', '\t', '\x00')) for text in drawn)
    assert any('line one line two control end' in text for text in drawn)
    assert json.loads((output / 'workflow.json').read_text())['status'] == 'complete'

    class Measurer:
        calls = 0

        def textlength(self, text, font):
            self.calls += 1
            assert self.calls <= 24, 'line fitting must not trim and remeasure one character at a time'
            return len(text)

    measurer = Measurer()
    fitted = custom_report._fit_line(measurer, 'X' * 140000, None, 60)
    assert len(fitted) <= 60 and fitted.endswith('...')


def test_legacy_batches_without_runner_timing_or_error_columns_are_supported(tmp_path, monkeypatch):
    summary = tmp_path / 'legacy.csv'
    assert experiment.main([str(SCENARIO), '--output', str(summary), '--planners', 'astar']) == 0
    rows = read_csv(summary)
    columns = [name for name in rows[0] if name not in {'runner_planning_time_ms', 'planning_error_type', 'planning_error_message', 'planning_error_truncated'}]
    with summary.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = tmp_path / 'legacy_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for key in ('experiment_revision', 'runner_planning_time_note', 'custom_planning_error_policy', 'planning_error_diagnostic_limits'):
        manifest.pop(key)
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    destination = tmp_path / 'legacy_analysis'
    assert analyze.main([str(summary), '--baseline', 'astar', '--output-dir', str(destination)]) == 0
    aggregate = read_csv(destination / 'planners.csv')[0]
    assert aggregate['runner_planning_time_ms'] == '' and aggregate['planning_errors'] == '0'
    drawn = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(self, xy, text, *args, **kwargs):
        drawn.append(text)
        return original_text(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', capture_text)
    assert custom_report.main([str(summary), '--output', str(tmp_path / 'legacy.png')]) == 0
    assert any('runner wall n/a' in text for text in drawn)
