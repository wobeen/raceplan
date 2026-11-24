"""Margin rescue contracts, the procedural development inputs, and the decision rule.

No planner runs on the development maps (seeds 1000-1011); planner fixtures are
synthetic and the runner smoke uses seed 1999, outside both reserved ranges.
"""
import importlib.util
import json
from math import atan2
from pathlib import Path

import numpy as np
import pytest

from raceplan.common import OccupancyGrid, Pose2D
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


def room(rows, columns):
    occupied = np.zeros((30, 30), dtype=bool)
    occupied[[0, -1], :] = occupied[:, [0, -1]] = True
    occupied[rows, columns] = True
    grid = OccupancyGrid(occupied, 0.2)
    return grid, grid.grid_to_world((3, 3), 0.0), grid.grid_to_world((26, 26))


def worst_clearance(grid, poses):
    clearance = Clearance(grid)
    dense = resample(poses, 0.02)
    return min(clearance.footprint(Pose2D(a.x, a.y, atan2(b.y - a.y, b.x - a.x)), baseline_vehicle())
               for a, b in zip(dense, dense[1:]))


def test_margins_apply_only_to_the_rescue_stage():
    for name, margin in (("MarginRescue08", 0.08), ("MarginRescue11", 0.11)):
        planner = load(name)
        assert planner.config.footprint_margin_m == margin
        assert planner.reference.config.footprint_margin_m == 0.02
        assert planner.rescue.base.config.footprint_margin_m == margin
        assert planner.rescue.base.config.target_clearance_m == 0.30
    with pytest.raises(ValueError, match="at least the reference"):
        type(load("MarginRescue08").config)(footprint_margin_m=0.01)


def test_accepted_reference_path_is_kept_even_below_the_rescue_margin():
    grid, start, goal = room(slice(8, 22), slice(8, 22))
    reference = load_custom_planner(f"{ROOT / 'examples/smoothed_astar_planner.py'}:SmoothedLowClearance")[0]
    expected = reference.plan(grid, start, goal)
    assert expected.metadata["smoothing"] == "accepted"
    result = load("MarginRescue11").plan(grid, start, goal)
    assert result.metadata["rescue"] == "not_needed" and result.path == expected.path


def test_rescued_path_keeps_the_raised_margin_or_falls_back_to_astar():
    grid, start, goal = room(slice(5, 25), slice(7, 23))
    for name, margin in (("MarginRescue08", 0.08), ("MarginRescue11", 0.11)):
        result = load(name).plan(grid, start, goal)
        if result.metadata["rescue"] == "lead_in":
            assert worst_clearance(grid, result.path.poses) >= margin - 0.01
        else:
            assert result.path == AStarPlanner().plan(grid, start, goal).path
    assert load("MarginRescue08").plan(grid, start, goal).metadata["rescue"] == "lead_in"


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
    report, bad = runner.novelty(generated, runner.committed_inventory())
    assert bad == [] and len({r["map_sha256"] for r in report}) == 12
    assert max(r["max_iou"] for r in report) < runner.NEAR_DUPLICATE_IOU
    assert min(min(r["endpoint_footprint_clearance_m"]) for r in report) >= runner.MIN_ENDPOINT_CLEARANCE_M


def test_novelty_flags_exact_and_near_duplicates():
    generated = {1999: runner.generate(1999)}
    grid = generated[1999][1]
    near = grid.occupied.copy()
    free = np.argwhere(~near)[:3]
    near[free[:, 0], free[:, 1]] = True
    inventory = {"exact.yaml": grid}, set()
    assert runner.novelty(generated, inventory)[1][0]["exact_map_duplicate"]
    close = runner.novelty(generated, ({"near.yaml": OccupancyGrid(near, 0.2)}, set()))[1]
    assert close and close[0]["max_iou"] >= runner.NEAR_DUPLICATE_IOU
    assert runner.novelty(generated, ({}, set()))[1] == []


def episodes(table):
    rows = []
    for case, by_planner in table.items():
        for planner in runner.PLANNERS:
            for seed in range(3):
                rows.append({"case": case, "planner": planner,
                             "failure_class": "reached" if seed < by_planner.get(planner, 0)
                             else "driving_collision"})
    return rows


def outcome(reference, m08, m11, astar=0, ablation=0, hybrid=0):
    return {"astar": astar, "hybrid_astar": hybrid, runner.REFERENCE: reference,
            runner.ABLATION: ablation, "margin_rescue_08": m08, "margin_rescue_11": m11}


def decide(table, rejected, rescued=None, mismatch=False):
    audit = [{"case": c, "planner": runner.REFERENCE, "matches_stored_path": True,
              "smoothing": "rejected" if c in rejected else "accepted", "rescue": ""}
             for c in table]
    for planner, cases in (rescued or {}).items():
        audit += [{"case": c, "planner": planner, "matches_stored_path": True,
                   "smoothing": "accepted", "rescue": "lead_in"} for c in cases]
    if mismatch:
        audit[0]["matches_stored_path"] = False
    return runner.decide(episodes(table), audit, {"margin_rescue_08": 5.0, "margin_rescue_11": 5.0})


def test_rejected_set_audit_and_required_gain():
    table = {f"a{i}": outcome(3, 3, 3) for i in range(10)}
    table |= {f"r{i}": outcome(0, 3 if i < 2 else 0, 3 if i < 3 else 0) for i in range(8)}
    rejected = {f"r{i}" for i in range(8)}
    result = decide(table, rejected)
    assert result["required_net_gain"] == 2 and result["selected"] == "margin_rescue_11"
    assert result["no_regression_evidence"] == "untestable"
    assert result["selection_label"] == "selected on gain only, regression untestable"
    assert decide(table, {"r0", "r1", "r2"})["verdict"] == "undecidable"
    assert decide(table, rejected, mismatch=True)["verdict"] == "invalid_audit"
    one = {f"a{i}": outcome(3, 3, 3) for i in range(10)}
    one |= {f"r{i}": outcome(0, 3 if i < 1 else 0, 3 if i < 1 else 0) for i in range(8)}
    assert decide(one, rejected)["verdict"] == "none"


def test_losses_tie_breaks_and_unselectable_planners():
    table = {f"a{i}": outcome(3, 0 if i == 0 else 3, 3, ablation=3, hybrid=3) for i in range(10)}
    table |= {f"r{i}": outcome(0, 3, 3 if i < 6 else 0, ablation=3, hybrid=3) for i in range(8)}
    rejected = {f"r{i}" for i in range(8)}
    result = decide(table, rejected)
    rows = {r["planner"]: r for r in result["candidates"]}
    assert rows["margin_rescue_08"]["losses_vs_reference"] == ["a0"]
    assert not rows[runner.ABLATION]["eligible"] and not rows["hybrid_astar"]["eligible"]
    assert result["selected"] == "margin_rescue_11"
    tie = {f"a{i}": outcome(3, 3, 3) for i in range(10)}
    tie |= {f"r{i}": outcome(0, 3 if i < 2 else 0, 3 if i < 2 else 0) for i in range(8)}
    assert decide(tie, rejected)["selected"] == "margin_rescue_08"
    more = decide(tie, rejected, rescued={"margin_rescue_11": ["r0", "r1"]})
    assert more["selected"] == "margin_rescue_11"
    fallback = dict(tie, r7=outcome(3, 0, 3), r6=outcome(3, 3, 3))
    regression = decide(fallback, rejected)
    assert regression["no_regression_evidence"] == "tested"
    assert regression["selected"] == "margin_rescue_11"


def test_run_writes_records_for_one_generator_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.previous, "repository_state", lambda _: {
        "run_commit": "test", "tracked_tree_dirty": False, "prereg_commit": "test"})
    monkeypatch.setattr(runner, "committed_inventory", lambda: ({}, set()))
    output = tmp_path / "out"
    assert 1999 not in runner.DEV_SEEDS and 1999 < runner.HELD_OUT_SEED_START
    summary, decision = runner.run(output, "test", seeds=(1999,))
    assert all(row["episodes"] == 6 for row in summary)
    assert decision["audit_all_match"] and decision["verdict"] == "undecidable"
    protocol = json.loads((output / "protocol.json").read_text(encoding="utf-8"))
    assert protocol["generator_seeds"] == [1999] and len(protocol["input_sha256"]) == 5
    for name in ("novelty.json", "protocol_start.json", "decision.json", "acceptance.csv"):
        assert (output / name).is_file()
    assert not (output / "aborted.json").exists()


def test_failure_mid_run_is_recorded_as_aborted(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.previous, "repository_state", lambda _: {
        "run_commit": "test", "tracked_tree_dirty": False, "prereg_commit": "test"})
    monkeypatch.setattr(runner, "committed_inventory", lambda: ({}, set()))
    monkeypatch.setattr(runner, "run_case", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        runner.run(tmp_path / "out", "test", seeds=(1999,))
    aborted = json.loads((tmp_path / "out" / "aborted.json").read_text(encoding="utf-8"))
    assert "boom" in aborted["error"] and (tmp_path / "out" / "protocol_start.json").is_file()
