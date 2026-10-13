"""Core recovery behavior: directional creep, actual-pose replan and finite budgets."""
from dataclasses import replace

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Path, PlannerResult, PlannerStatus, Pose2D
from raceplan.defaults import baseline_simulation_config, baseline_tracker_config, baseline_vehicle
from raceplan.simulator import RecoveryConfig, SimulationStatus, run_episode
from raceplan.simulator.obstacle_guard import ObstacleGuardConfig
from raceplan.simulator.kinematic import replan_feasible
from raceplan.simulator.recovery import PathProgress, path_prefix, repeated_path


def test_parallel_wall_restarts_without_changing_baseline_guard():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[20, :] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(1, 2.3), Pose2D(5, 2.3)
    args = (grid, Path((start, goal), 4), goal, baseline_vehicle(),
            baseline_tracker_config(), baseline_simulation_config())
    guarded = run_episode(*args, obstacle_guard=ObstacleGuardConfig())
    recovered = run_episode(*args, obstacle_guard=ObstacleGuardConfig(), recovery=RecoveryConfig())
    assert guarded.status is SimulationStatus.TIMEOUT
    assert recovered.reached and not recovered.collided
    assert recovered.goal_distance <= .5
    assert recovered.restart_count == 1 and recovered.replan_count == 0
    assert recovered.stopped_time_s > 0
    assert recovered.driving_time_s + recovered.stopped_time_s == pytest.approx(recovered.completion_time_s)


@pytest.mark.parametrize('no_path', [True, False])
def test_blocked_forward_replans_from_stopped_pose_and_terminates(no_path):
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(3, 3), Pose2D(6, 3)
    calls = []
    def replan(pose, destination):
        calls.append((pose, destination))
        if no_path:
            return PlannerResult(PlannerStatus.NO_PATH, planning_time_s=.2)
        # Returning the same blocked path must consume the budget, never loop forever.
        return PlannerResult(PlannerStatus.SUCCESS, Path((pose, destination), 3), planning_time_s=.2)
    result = run_episode(grid, Path((start, goal), 3), goal, baseline_vehicle(),
                         baseline_tracker_config(),
                         replace(baseline_simulation_config(), max_time_s=10),
                         obstacle_guard=ObstacleGuardConfig(),
                         recovery=RecoveryConfig(max_restarts=0, max_replans=1), replanner=replan)
    assert result.status is (SimulationStatus.PLANNING_FAILED if no_path else SimulationStatus.RECOVERY_FAILED)
    assert not result.collided and not result.reached
    assert result.replan_count == len(calls) == 1
    assert calls[0][1] == goal and calls[0][0] != start
    event = next(e for e in result.recovery_events if e.kind == 'replan')
    assert event.pose == calls[0][0]
    at_event = next(s for s in result.samples if s.time_s == pytest.approx(event.time_s))
    assert at_event.state.speed == 0 and at_event.state.pose == event.pose
    assert result.replanning_time_s == pytest.approx(.2)
    assert result.completion_time_s < 10


def test_path_progress_credits_detour_and_does_not_credit_backtracking():
    start, away, goal = Pose2D(2, 2), Pose2D(1, 2), Pose2D(1, 4)
    progress = PathProgress(Path((start, away, goal), 3), start)
    # A legitimate forward segment initially increases straight goal distance.
    assert progress.update(Pose2D(1.7, 2)) == pytest.approx(.3)

    # A replan that trims the traversed part and changes sampling is still the
    # same blocked forward geometry at the stopped pose.
    pose = Pose2D(2.5, 2)
    original = Path((Pose2D(1, 2), Pose2D(6, 2)), 5)
    trimmed = Path((pose, Pose2D(3, 2), Pose2D(6, 2)), 3.5)
    assert repeated_path(path_prefix(original, pose), path_prefix(trimmed, pose), .1)
    assert progress.update(start) == pytest.approx(0)
    assert progress.update(Pose2D(1.7, 2)) == pytest.approx(.3)


def test_creep_resumes_only_after_sustained_native_guard_headroom():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[20, :25] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(1, 2.3), Pose2D(5, 2.3)
    result = run_episode(grid, Path((start, goal), 4), goal, baseline_vehicle(),
                         baseline_tracker_config(), baseline_simulation_config(),
                         obstacle_guard=ObstacleGuardConfig(), recovery=RecoveryConfig())
    assert result.reached and not result.collided
    restart = next(e for e in result.recovery_events if e.kind == 'restart')
    resume = next(e for e in result.recovery_events if e.kind == 'resume')
    assert resume.time_s-restart.time_s >= RecoveryConfig().resume_dwell_s
    assert max(s.state.speed for s in result.samples if s.time_s > resume.time_s) > .25


def test_candidate_preview_uses_tracker_guard_without_mutating_input_pose():
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    pose, goal = Pose2D(3, 3), Pose2D(6, 3)
    assert not replan_feasible(grid, Path((pose, goal), 3), goal, pose,
                               baseline_vehicle(), baseline_tracker_config(),
                               baseline_simulation_config(), ObstacleGuardConfig(), RecoveryConfig())
    assert pose == Pose2D(3, 3)
