import csv
import json
from pathlib import Path

import pytest

from raceplan.analyze import main as analyze
from raceplan.experiment import main as run


def test_saved_batch_analysis_and_incomplete_pair_rejection(tmp_path):
    scenario = Path(__file__).resolve().parents[1] / 'scenarios/validation_open.yaml'
    summary = tmp_path / 'batch.csv'
    run([str(scenario), '--output', str(summary), '--planners', 'dijkstra', 'astar',
         '--simulation-seeds', '0', '1'])
    destination = tmp_path / 'analysis'
    assert analyze([str(summary), '--output-dir', str(destination)]) == 0
    with (destination / 'paired.csv').open(newline='') as stream:
        pairs = list(csv.DictReader(stream))
    assert len(pairs) == 2
    assert all(float(row['delta_tracking_rmse_m']) == 0.0 for row in pairs)
    assert all(float(row['delta_driving_min_sampled_clearance_m']) == 0.0 for row in pairs)
    with (destination / 'clearance_samples.csv').open(newline='') as stream:
        clearance_samples = list(csv.DictReader(stream))
    with (destination / 'episodes.csv').open(newline='') as stream:
        episodes = list(csv.DictReader(stream))
    for episode in episodes:
        recorded = [float(s['footprint_clearance_m']) for s in clearance_samples
                    if s['episode_id'] == episode['episode_id']]
        assert float(episode['driving_min_sampled_clearance_m']) == min(recorded)
    with (destination / 'planners.csv').open(newline='') as stream:
        planners = list(csv.DictReader(stream))
    assert all(float(row['reach_rate']) == 1.0 for row in planners)
    provenance = json.loads((destination / 'analysis.json').read_text())
    assert provenance['requested_spacing_m'] == 0.1
    trajectory = summary.with_name('batch_trajectory.csv')
    original_trajectory = trajectory.read_text()
    trajectory.write_text('\n'.join(original_trajectory.splitlines()[:-1]) + '\n')
    with pytest.raises(ValueError, match='times'):
        analyze([str(summary), '--output-dir', str(tmp_path / 'truncated')])
    assert not (tmp_path / 'truncated').exists()
    trajectory.write_text(original_trajectory)
    lines = summary.read_text().splitlines()
    summary.write_text('\n'.join(lines[:-1]) + '\n')
    with pytest.raises(ValueError, match='coverage'):
        analyze([str(summary), '--output-dir', str(tmp_path / 'incomplete')])
    assert not (tmp_path / 'incomplete').exists()


def test_initial_collision_is_in_clearance_aggregation(tmp_path, monkeypatch):
    from dataclasses import replace
    import raceplan.experiment as experiment
    from raceplan.defaults import baseline_vehicle

    monkeypatch.setattr(experiment, 'baseline_vehicle', lambda: replace(baseline_vehicle(), width=10.0))
    scenario = Path(__file__).resolve().parents[1] / 'scenarios/validation_open.yaml'
    summary = tmp_path / 'collision.csv'
    run([str(scenario), '--output', str(summary), '--planners', 'dijkstra'])
    destination = tmp_path / 'analysis'
    analyze([str(summary), '--output-dir', str(destination)])
    with (destination / 'planners.csv').open(newline='') as stream:
        planner = next(csv.DictReader(stream))
    assert planner['initial_collisions'] == '1'
    assert planner['driven_episodes'] == '1'
    assert planner['success_tracking_rmse_m_median'] == ''
    assert float(planner['all_driven_min_clearance_m_min']) == 0.0
