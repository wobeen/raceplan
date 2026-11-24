"""Margin rescue contracts, the procedural development inputs, and the decision rule.

No planner runs on the development maps here; planner fixtures are synthetic.
"""
import importlib.util
import json
from math import atan2
from pathlib import Path

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Pose2D, footprint_in_collision
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import Clearance, resample
from raceplan.planners import AStarPlanner
from raceplan.planners.custom import load_custom_planner

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "examples/margin_rescue_planner.py"
SPEC = importlib.util.spec_from_file_location("margin_dev", ROOT / "results/margin_rescue_development.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def load(name):
    return load_custom_planner(f"{PLUGIN}:{name}")[0]


def narrow_room():
    """The plain post-processing is rejected here; a lead-in clears the wider margin."""
    occupied = np.zeros((30, 30), dtype=bool)
    occupied[[0, -1], :] = occupied[:, [0, -1]] = True
    occupied[5:25, 7:23] = True
    grid = OccupancyGrid(occupied, 0.2)
    return grid, grid.grid_to_world((3, 3), 0.0), grid.grid_to_world((26, 26))


def test_margins_are_applied_to_every_verification():
    for name, margin in (("MarginRescue08", 0.08), ("MarginRescue11", 0.11)):
        planner = load(name)
        assert planner.config.footprint_margin_m == margin
        assert planner.base.config.footprint_margin_m == margin
        assert planner.base.config.target_clearance_m == 0.30
    assert load("MarginOnly08").config.footprint_margin_m == 0.08


def test_rescued_path_keeps_the_raised_margin_and_ablation_falls_back_to_astar():
    grid, start, goal = narrow_room()
    planner = load("MarginRescue08")
    result = planner.plan(grid, start, goal)
    assert result.metadata["rescue"] == "lead_in"
    clearance = Clearance(grid)
    dense = resample(result.path.poses, 0.02)
    worst = min(clearance.footprint(Pose2D(a.x, a.y, atan2(b.y - a.y, b.x - a.x)), baseline_vehicle())
                for a, b in zip(dense, dense[1:]))
    assert worst >= 0.08 - 0.01
    ablation = load("MarginOnly08").plan(grid, start, goal)
    assert ablation.metadata["smoothing"] == "rejected"
    assert ablation.path == AStarPlanner().plan(grid, start, goal).path


def test_generator_is_deterministic_and_reserves_held_out_seeds():
    first, second = runner.generate(1003), runner.generate(1003)
    assert first[0] == second[0] and np.array_equal(first[1].occupied, second[1].occupied)
    assert first[2] == second[2]
    with pytest.raises(ValueError, match="reserved"):
        runner.generate(runner.HELD_OUT_SEED_START)
    assert max(runner.DEV_SEEDS) < runner.HELD_OUT_SEED_START


def test_development_inputs_are_valid_and_new():
    generated = {seed: runner.generate(seed) for seed in runner.DEV_SEEDS}
    families = [family for family, *_ in generated.values()]
    assert {f: families.count(f) for f in runner.FAMILIES} == {f: 4 for f in runner.FAMILIES}
    assert sum(len(pairs) for _, _, pairs, _ in generated.values()) == 24
    for _, grid, pairs, _ in generated.values():
        for start, goal in pairs:
            for pose in (start, goal):
                assert not footprint_in_collision(grid, pose, baseline_vehicle())
    report, bad = runner.novelty(generated, runner.committed_inventory())
    assert bad == [] and len({r["map_sha256"] for r in report}) == 12
    assert max(r["max_iou"] for r in report) < runner.NEAR_DUPLICATE_IOU


def episodes(table):
    rows = []
    for case, by_planner in table.items():
        for planner in runner.PLANNERS:
            for seed in range(3):
                rows.append({"case": case, "planner": planner,
                             "failure_class": "reached" if seed < by_planner.get(planner, 0)
                             else "driving_collision"})
    return rows


def outcome(reference, m08, m11, astar=0, ablation=0, previous=0, hybrid=0):
    return {"astar": astar, "hybrid_astar": hybrid, runner.REFERENCE: reference,
            runner.PREVIOUS: previous, "margin_rescue_08": m08, "margin_rescue_11": m11,
            runner.ABLATION: ablation}


def decide(table, mismatch=False, p95=None):
    audit = [{"case": c, "planner": runner.REFERENCE, "smoothing": "accepted",
              "matches_stored_path": True} for c in table]
    if mismatch:
        audit[0]["matches_stored_path"] = False
    return runner.decide(episodes(table), audit, p95 or {"margin_rescue_08": 5.0,
                                                         "margin_rescue_11": 5.0})


def test_reference_stratum_audit_and_required_gain():
    table = {f"q{i}": outcome(3 if i < 5 else 0, 3, 3) for i in range(24)}
    assert decide(table)["verdict"] == "undecidable"
    table["q5"] = outcome(3, 3, 3)
    result = decide(table)
    assert result["required_net_gain"] == 3 and result["verdict"] == "selected"
    assert result["selected"] == "margin_rescue_08"
    assert decide(table, mismatch=True)["verdict"] == "invalid_audit"
    few = {f"q{i}": outcome(3 if i < 6 else 0, 3 if i < 8 else 0, 0) for i in range(24)}
    assert decide(few)["verdict"] == "none"


def test_losses_block_selection_and_reported_planners_are_never_selected():
    table = {f"q{i}": outcome(3 if i < 6 else 0, 0 if i == 0 else 3, 3,
                              ablation=3, previous=3, hybrid=3) for i in range(24)}
    result = decide(table)
    rows = {r["planner"]: r for r in result["candidates"]}
    assert rows["margin_rescue_08"]["losses_vs_reference"] == ["q0"]
    assert not any(rows[p]["eligible"] for p in (runner.ABLATION, runner.PREVIOUS, "hybrid_astar"))
    assert result["selected"] == "margin_rescue_11"
    astar = dict(table, q23=outcome(0, 3, 0, astar=3))
    assert decide(astar)["verdict"] == "none"


def test_run_writes_records_for_one_generator_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.previous, "repository_state", lambda _: {
        "run_commit": "test", "tracked_tree_dirty": False, "prereg_commit": "test"})
    monkeypatch.setattr(runner, "committed_inventory", lambda: ({}, set()))
    output = tmp_path / "out"
    # 1999 is outside both the development range and the reserved held-out range.
    assert 1999 not in runner.DEV_SEEDS and 1999 < runner.HELD_OUT_SEED_START
    summary, decision = runner.run(output, "test", seeds=(1999,))
    assert all(row["episodes"] == 6 for row in summary)
    assert decision["audit_all_match"] and decision["verdict"] == "undecidable"
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["generator_seeds"] == [1999] and len(protocol["input_sha256"]) == 5
    for name in ("novelty.json", "protocol_start.json", "decision.json", "acceptance.csv"):
        assert (output / name).is_file()
