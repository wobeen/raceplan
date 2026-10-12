"""Focused regressions for seed pairing and failed-episode persistence."""
import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import raceplan.experiment as experiment
from raceplan.common import OccupancyGrid, Path as PlannedPath, PlannerResult, PlannerStatus, Pose2D
from raceplan.defaults import baseline_simulation_config, baseline_tracker_config, baseline_vehicle
from raceplan.simulator import NoiseConfig, run_episode


def test_seeded_driving_repeats_and_zero_noise_ignores_seed():
    grid = OccupancyGrid(np.zeros((6, 9), dtype=bool), resolution=1.0)
    path = PlannedPath((Pose2D(1.5, 2.5), Pose2D(6.5, 2.5)), cost=5.0)
    args = (grid, path, path.poses[-1], baseline_vehicle(), baseline_tracker_config(),
            baseline_simulation_config())
    noise = NoiseConfig(0.02, 0.01, 0.01, 0.01, 0.02)
    first = run_episode(*args, simulation_seed=7, noise=noise)
    assert first == run_episode(*args, simulation_seed=7, noise=noise)
    assert first.samples != run_episode(*args, simulation_seed=8, noise=noise).samples
    assert run_episode(*args, simulation_seed=7) == run_episode(*args, simulation_seed=8)


def test_batch_reuses_plans_pairs_starts_and_preserves_failures(tmp_path, monkeypatch):
    calls = []

    class StubPlanner:
        def __init__(self, name, status):
            self.name, self.status = name, status

        def plan(self, grid, start, goal, *, timeout_s):
            calls.append((self.name, start, goal, timeout_s))
            if self.status != PlannerStatus.SUCCESS:
                return PlannerResult(self.status)
            # Deliberately differs from scenario start: actual starts must still pair.
            return PlannerResult(self.status, PlannedPath((Pose2D(2.5, 1.5), goal), 5.0))

    monkeypatch.setattr(experiment, 'PLANNER_FACTORIES', {
        name: (lambda name=name, status=status: StubPlanner(name, status))
        for name, status in [('first', PlannerStatus.SUCCESS), ('second', PlannerStatus.SUCCESS),
                             ('failed', PlannerStatus.NO_PATH)]
    })
    # A short duration exercises timeout trajectory storage.
    monkeypatch.setattr(experiment, 'baseline_simulation_config',
                        lambda: replace(baseline_simulation_config(), max_time_s=0.1))
    scenario = Path(__file__).resolve().parents[1] / 'scenarios/demo.yaml'
    output = tmp_path / 'batch.csv'
    arguments = [str(scenario), '--output', str(output), '--simulation-seeds', '7', '8',
                 '--initial-position-std-m', '0.02']
    assert experiment.main(arguments) == 0
    assert len(calls) == 3
    assert all(call[1:] == calls[0][1:] for call in calls)
    with output.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert [row['simulation_status'] for row in rows] == ['timeout'] * 4 + ['not_run'] * 2
    with output.with_name('batch_trajectory.csv').open(newline='') as stream:
        samples = list(csv.DictReader(stream))
    for seed in (7, 8):
        first = [r for r in samples if r['episode_id'] == f'first:{seed}']
        second = [r for r in samples if r['episode_id'] == f'second:{seed}']
        assert len(first) == len(second) == 3
        assert [{k: v for k, v in r.items() if k != 'episode_id'} for r in first] == [
            {k: v for k, v in r.items() if k != 'episode_id'} for r in second]
        assert abs(float(first[0]['x_m']) - 1.5) < 0.2
    assert not any(r['episode_id'].startswith('failed') for r in samples)
    manifest = json.loads(output.with_name('batch_manifest.json').read_text())
    assert manifest['status'] == 'complete'
    assert manifest['planning_repetitions'] == 1
    with pytest.raises(SystemExit):
        experiment.main(arguments)
    assert len(calls) == 3  # Overwrite rejected before planning.

    # Same runner also persists the initial sample of a collision failure.
    monkeypatch.setattr(experiment, 'baseline_vehicle',
                        lambda: replace(baseline_vehicle(), width=10.0))
    collision_output = tmp_path / 'collision.csv'
    assert experiment.main([str(scenario), '--output', str(collision_output),
                            '--planners', 'first']) == 0
    with collision_output.open(newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['simulation_status'] == 'collision'
    with collision_output.with_name('collision_trajectory.csv').open(newline='') as stream:
        collision_samples = list(csv.DictReader(stream))
    assert len(collision_samples) == 1
    assert collision_samples[0]['time_s'] == '0.0'
