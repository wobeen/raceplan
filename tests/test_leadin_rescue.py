"""Lead-in rescue contracts and the pre-registered development decision rule.

No test runs a planner on the development inputs; fixtures are synthetic grids.
"""
import importlib.util
import json
from math import atan2, cos, sin
from pathlib import Path
import sys

import numpy as np
from PIL import Image
import pytest
import yaml

from raceplan.common import OccupancyGrid, PlannerStatus, Pose2D
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import Clearance, path_metrics, resample
from raceplan.planners import AStarPlanner
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "examples/leadin_rescue_planner.py"
SPEC = importlib.util.spec_from_file_location("leadin_dev", ROOT / "results/leadin_rescue_development.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def load(name="LeadInRescueK3"):
    return load_custom_planner(f"{PLUGIN}:{name}")[0]


def bordered(rows=36, columns=52):
    occupied = np.zeros((rows, columns), dtype=bool)
    occupied[[0, -1], :] = occupied[:, [0, -1]] = True
    return occupied


def wall_ahead():
    """A wall 1.3 m ahead of an east-facing start forces an immediate right turn."""
    occupied = bordered()
    occupied[10:, 12:15] = True
    return OccupancyGrid(occupied, 0.2), Pose2D(1.1, 5.6, 0.0), Pose2D(9.3, 1.1)


def test_arc_points_follow_the_analytic_circle():
    module = type(load()).__module__
    arc_points = __import__("sys").modules[module].arc_points
    start = Pose2D(1.0, 2.0, 0.3)
    points, headings = arc_points(start, -1.2, 1.0, 0.1)
    radius = 1 / 1.2
    centre = (start.x + radius * sin(start.yaw), start.y - radius * cos(start.yaw))
    assert np.allclose(np.hypot(points[:, 0] - centre[0], points[:, 1] - centre[1]), radius)
    assert headings[-1] == pytest.approx(start.yaw - 1.2)
    straight, _ = arc_points(start, 0.0, 0.5, 0.1)
    assert straight[-1] == pytest.approx((start.x + 0.5 * cos(0.3), start.y + 0.5 * sin(0.3)))


def test_accepted_base_result_is_returned_unchanged():
    occupied = bordered(30, 30)
    occupied[8:22, 8:22] = True
    grid = OccupancyGrid(occupied, 0.2)
    start, goal = grid.grid_to_world((5, 5), 0.0), grid.grid_to_world((24, 24))
    reference = load_custom_planner(f"{ROOT / 'examples/smoothed_astar_planner.py'}:SmoothedLowClearance")[0]
    expected = reference.plan(grid, start, goal)
    result = load().plan(grid, start, goal)
    assert expected.metadata["smoothing"] == "accepted"
    assert result.metadata["rescue"] == "not_needed" and result.path == expected.path


def test_rescued_path_passes_independent_footprint_and_curvature_checks():
    grid, start, goal = wall_ahead()
    planner = load()
    result = planner.plan(grid, start, goal)
    assert result.status is PlannerStatus.SUCCESS and result.metadata["rescue"] == "lead_in"
    poses = result.path.poses
    # The first chord of a lead-in arc deviates from the start yaw by at most kappa * ds / 2.
    first_heading = atan2(poses[1].y - poses[0].y, poses[1].x - poses[0].x)
    assert abs(first_heading - start.yaw) <= planner.base.config.max_curvature_per_m * 0.1 / 2
    limit = planner.base.config.max_curvature_per_m
    assert path_metrics(poses, grid, baseline_vehicle(), start, goal)["max_discrete_curvature_per_m"] <= limit
    clearance = Clearance(grid)
    dense = resample(poses, 0.02)
    for a, b in zip(dense, dense[1:]):
        pose = Pose2D(a.x, a.y, atan2(b.y - a.y, b.x - a.x))
        assert clearance.footprint(pose, baseline_vehicle()) >= planner.base.config.footprint_margin_m - 0.01


def test_failed_rescue_returns_the_unmodified_astar_path():
    grid, start, goal = wall_ahead()
    result = load("LeadInStraight").plan(grid, start, goal)
    assert result.metadata["rescue"] == "failed" and result.metadata["smoothing"] == "rejected"
    assert result.path == AStarPlanner().plan(grid, start, goal).path


def test_invalid_configuration_and_timeout():
    config = type(load().config)
    with pytest.raises(ValueError, match="odd"):
        config(curvatures=4)
    with pytest.raises(ValueError, match="lengths_m"):
        config(lengths_m=())
    grid, start, goal = wall_ahead()
    assert load().plan(grid, start, goal, timeout_s=0).status is PlannerStatus.TIMEOUT


def test_running_out_of_time_during_rescue_keeps_the_base_fallback(monkeypatch):
    planner = load()
    monkeypatch.setattr(sys.modules[type(planner).__module__], "smooth_rest", lambda *args: None)
    grid, start, goal = wall_ahead()
    result = planner.plan(grid, start, goal, timeout_s=30)
    assert result.status is PlannerStatus.SUCCESS and result.metadata["rescue"] == "timeout"
    assert result.path == AStarPlanner().plan(grid, start, goal).path


def episodes(outcomes):
    """``outcomes[case][planner]`` = reached seed count (0-3)."""
    rows = []
    for case, by_planner in outcomes.items():
        for planner in runner.PLANNERS:
            for seed in range(3):
                reached = seed < by_planner.get(planner, 0)
                rows.append({"case": case, "planner": planner,
                             "failure_class": "reached" if reached else "driving_collision"})
    return rows


def outcome(reference, k3, k6, ablation, astar=0):
    return {"astar": astar, "hybrid_astar": 0, runner.REFERENCE: reference,
            "leadin_rescue_k3": k3, "leadin_rescue_k6": k6, "leadin_straight": ablation}


def decide(table, rejected=(), accepted=None, p95=None, mismatch=False):
    """Audit rows: the reference is rejected on ``rejected``; ``accepted`` counts per candidate."""
    accepted = accepted or {}
    audit = []
    for case in table:
        audit.append({"case": case, "planner": runner.REFERENCE, "matches_stored_path": True,
                      "smoothing": "rejected" if case in rejected else "accepted"})
    for planner, count in accepted.items():
        audit += [{"case": f"extra{i}", "planner": planner, "smoothing": "accepted",
                   "matches_stored_path": True} for i in range(count)]
    if mismatch:
        audit[0]["matches_stored_path"] = False
    return runner.decide(episodes(table), audit, p95 or {
        "leadin_rescue_k3": 10.0, "leadin_rescue_k6": 20.0, "leadin_straight": 5.0})


def test_too_few_rejected_queries_or_an_audit_mismatch_blocks_any_selection():
    table = {f"q{i}": outcome(3, 3, 3, 3) for i in range(5)}
    table |= {f"r{i}": outcome(0, 3, 3, 3) for i in range(3)}
    few = decide(table, rejected={"r0", "r1", "r2"})
    assert few["verdict"] == "undecidable" and not any(r["eligible"] for r in few["candidates"])
    table["r3"] = outcome(0, 3, 3, 3)
    rejected = {"r0", "r1", "r2", "r3"}
    assert decide(table, rejected=rejected)["verdict"] == "selected"
    assert decide(table, rejected=rejected, mismatch=True)["verdict"] == "invalid_audit"


def test_any_lost_query_makes_a_candidate_ineligible_and_ablation_is_never_selected():
    table = {f"q{i}": outcome(3, 3, 2 if i else 1, 3) for i in range(5)}
    table |= {f"g{i}": outcome(0, 2, 3, 3) for i in range(4)}
    result = decide(table, rejected={"g0", "g1", "g2", "g3"})
    rows = {r["planner"]: r for r in result["candidates"]}
    assert rows["leadin_rescue_k6"]["losses_vs_reference"] == ["q0"]
    assert not rows["leadin_rescue_k6"]["eligible"] and not rows["leadin_straight"]["eligible"]
    assert result["selected"] == "leadin_rescue_k3"


def test_required_gain_scales_with_the_rejected_set_and_tie_breaks():
    base = {f"q{i}": outcome(3, 3, 3, 0) for i in range(5)}
    rejected = {f"r{i}" for i in range(12)}
    two = base | {f"r{i}": outcome(0, 3 if i < 2 else 0, 3 if i < 2 else 0, 0) for i in range(12)}
    result = decide(two, rejected=rejected)
    assert result["required_net_gain"] == 3 and result["verdict"] == "none"
    three = base | {f"r{i}": outcome(0, 3 if i < 3 else 0, 3 if i < 3 else 0, 0) for i in range(12)}
    assert decide(three, rejected=rejected)["selected"] == "leadin_rescue_k3"
    more_accepted = decide(three, rejected=rejected,
                           accepted={"leadin_rescue_k6": 2, "leadin_rescue_k3": 1})
    assert more_accepted["selected"] == "leadin_rescue_k6"
    astar_loss = three | {"a0": outcome(0, 0, 3, 0, astar=3)}
    assert decide(astar_loss, rejected=rejected)["selected"] == "leadin_rescue_k6"


def test_regression_evidence_needs_rejected_queries_the_fallback_reaches():
    table = {f"r{i}": outcome(3 if i < 2 else 0, 3, 3, 0) for i in range(6)}
    tested = decide(table, rejected=set(table))
    assert tested["no_regression_evidence"] == "tested" and tested["selection_label"] == ""
    table["r1"] = outcome(0, 3, 3, 0)
    untested = decide(table, rejected=set(table))
    assert untested["no_regression_evidence"] == "untestable"
    assert untested["selection_label"] == "selected on gain only, regression untestable"


def test_runner_refuses_a_dirty_tracked_tree(monkeypatch):
    monkeypatch.setattr(runner, "git", lambda *args: " M examples/x.py" if args[0] == "status" else "")
    with pytest.raises(ValueError, match="modified"):
        runner.repository_state("HEAD")


def test_inputs_are_the_twenty_exposed_queries():
    assert len(runner.INPUTS) == len(set(runner.INPUTS)) == 20
    assert len({runner.case_name(name) for name in runner.INPUTS}) == 20
    for name in runner.INPUTS:
        assert (ROOT / name).is_file()
        assert name.startswith((runner.TURN_AWARE, runner.SMOOTHING))


def test_run_writes_protocol_audit_and_decision_on_a_synthetic_query(tmp_path, monkeypatch):
    grid, start, goal = wall_ahead()
    Image.fromarray(np.flipud(np.where(grid.occupied, 0, 255)).astype("uint8")).save(tmp_path / "map.pgm")
    (tmp_path / "map.yaml").write_text(
        "image: map.pgm\nresolution: 0.2\norigin: [0.0, 0.0, 0.0]\nsource: test\nlicense: CC0-1.0\n",
        encoding="utf-8")
    scenario = tmp_path / "q.yaml"
    scenario.write_text(yaml.safe_dump({
        "name": "synthetic", "map": "map.yaml", "start": [start.x, start.y, start.yaw],
        "goal": [goal.x, goal.y, goal.yaw], "map_seed": None, "simulation_seed": 1,
        "timeout_s": 5.0}), encoding="utf-8")
    monkeypatch.setattr(runner, "repository_state", lambda _: {
        "run_commit": "test", "tracked_tree_dirty": False, "prereg_commit": "test"})
    output = tmp_path / "out"
    summary, decision = runner.run(output, "test", inputs=[str(scenario)])
    assert {row["planner"] for row in summary} == set(runner.PLANNERS)
    assert all(row["episodes"] == 3 for row in summary)
    assert decision["audit_all_match"] and decision["verdict"] == "undecidable"
    assert decision["reference_rejected_queries"]
    for name in ("protocol_start.json", "protocol.json", "decision.json", "acceptance.csv"):
        assert (output / name).is_file()
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["uv_lock_sha256"] and len(protocol["input_sha256"]) == 3
