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


@pytest.mark.parametrize('version', [3, 4])
def test_v3_alternatives_are_lazy_bounded_and_keep_stopped_pose(version):
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(3, 3), Pose2D(6, 3)
    calls = []
    def replan(pose, destination):
        return PlannerResult(PlannerStatus.SUCCESS, Path((pose, destination), 3))
    def alternatives(pose, destination):
        for index in range(20):
            calls.append((index, pose, destination))
            yield replan(pose, destination)
    result = run_episode(grid, Path((start, goal), 3), goal, baseline_vehicle(),
                         baseline_tracker_config(), baseline_simulation_config(),
                         obstacle_guard=ObstacleGuardConfig(),
                         recovery=RecoveryConfig(policy_version=version, max_restarts=0,
                                                 max_alternatives=2),
                         replanner=replan, alternative_replanner=alternatives)
    assert result.status is SimulationStatus.RECOVERY_FAILED
    assert result.recovery_reason == 'alternative_budget_exhausted'
    assert len(calls) == 2 and result.replan_count == 1
    assert all(p == result.samples[-1].state.pose and g == goal for _, p, g in calls)
    assert result.samples[-1].state.speed == 0
    assert sum(e.kind == 'alternative_rejected' for e in result.recovery_events) == 2


@pytest.mark.parametrize('version', [3, 4])
def test_v3_accepts_first_trackable_alternative_and_resets_without_teleport(monkeypatch, version):
    occupied = np.zeros((60, 80), dtype=bool)
    occupied[:, 40] = True
    grid = OccupancyGrid(occupied, .1)
    start, goal = Pose2D(3, 3), Pose2D(6, 3)
    accepted = []
    def replan(pose, destination):
        return PlannerResult(PlannerStatus.SUCCESS, Path((pose, destination), 3))
    def alternatives(pose, destination):
        path = Path((pose, Pose2D(pose.x, pose.y+1), destination), 4)
        accepted.append(path)
        yield PlannerResult(PlannerStatus.SUCCESS, path)
        raise AssertionError('must stop generating after acceptance')
    # Selection contract only; real physical feasibility remains covered above.
    monkeypatch.setattr('raceplan.simulator.kinematic.replan_feasible', lambda *args: True)
    result = run_episode(grid, Path((start, goal), 3), goal, baseline_vehicle(),
                         baseline_tracker_config(), baseline_simulation_config(),
                         obstacle_guard=ObstacleGuardConfig(),
                         recovery=RecoveryConfig(policy_version=version, max_restarts=0, max_replans=1),
                         replanner=replan, alternative_replanner=alternatives)
    event = next(e for e in result.recovery_events if e.kind == 'alternative_accepted')
    assert event.path == accepted[0] and event.path.poses[0] == event.pose
    before = next(s for s in result.samples if abs(s.time_s-event.time_s) < 1e-8)
    after = next(s for s in result.samples if abs(s.time_s-event.time_s-.05) < 1e-8)
    assert before.state.speed == after.state.speed == 0
    assert before.state.pose == after.state.pose == event.pose


def test_v4_exact_clearance_and_shared_node_budget(monkeypatch):
    from raceplan.metrics import Clearance
    from raceplan.planners.recovery_alternatives import _ExactClearanceCache, forward_alternatives
    from raceplan.research_engine import planner
    grid = OccupancyGrid(np.zeros((100, 100), dtype=bool), .1)
    vehicle = baseline_vehicle()
    cache = _ExactClearanceCache(grid, max_entries=2)
    poses = (Pose2D(3, 3), Pose2D(3, 3, .3), Pose2D(3.000000000001, 3))
    geometry = Clearance(grid)
    for pose in poses:
        assert cache.footprint(pose, vehicle) == geometry.footprint(pose, vehicle)
    assert len(cache.values) == 2
    assert cache.footprint(poses[-1], vehicle) == geometry.footprint(poses[-1], vehicle)
    assert cache.hits == 1 and cache.misses == 3
    calls = []
    def exhausted(self, *args, **kwargs):
        calls.append((self.config.max_expanded_nodes, kwargs['clearance_evaluator']))
        return PlannerResult(PlannerStatus.TIMEOUT, expanded_nodes=4000)
    monkeypatch.setattr('raceplan.planners.hybrid_astar.HybridAStarPlanner.plan', exhausted)
    candidates = list(forward_alternatives(planner('hybrid_astar'), grid,
                     poses[0], Pose2D(7, 3), policy_version=4, timeout_s=100))
    assert len(calls) == 1 and calls[0][0] == 4000
    assert candidates[-1].metadata['reason'] == 'request_budget_exhausted'
    assert sum(c.expanded_nodes for c in candidates) == 4000
