"""Held-out runner: generator, novelty, stratified selection, verdict, and records.

Tests generate pool maps but never plan or drive on pool seeds (2000-2059); the
runner smoke uses seeds 1997/1998, outside the pool and development ranges.
"""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("leadin_holdout", ROOT / "results/leadin_holdout.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def test_generator_is_deterministic_and_refuses_development_seeds():
    first, second = runner.generate(2005), runner.generate(2005)
    assert first[0] == second[0] and np.array_equal(first[1].occupied, second[1].occupied)
    assert first[2] == second[2]
    with pytest.raises(ValueError, match="development"):
        runner.generate(runner.development.DEV_SEEDS[0])
    families = [runner.generate(seed)[0] for seed in runner.POOL_SEEDS[:6]]
    assert families == list(runner.development.FAMILIES) * 2
    assert not set(runner.POOL_SEEDS) & set(runner.DEVELOPMENT_GENERATED + runner.SMOKE_SEEDS)


def test_pool_keeps_twenty_novel_maps_per_family_in_seed_order():
    pool, report, skipped = runner.build_pool(runner.POOL_SEEDS, runner.inventory_with_development())
    families = [family for family, *_ in pool.values()]
    assert {f: families.count(f) for f in runner.development.FAMILIES} == {
        f: runner.PER_FAMILY for f in runner.development.FAMILIES}
    assert list(pool) == sorted(pool) and min(pool) == 2000
    assert all(r["max_iou"] >= runner.development.NEAR_DUPLICATE_IOU or r["exact_map_duplicate"]
               for r in skipped)
    _, bad = runner.development.novelty(
        {s: (f, g, [p for p in pairs if p], r) for s, (f, g, pairs, r) in pool.items()},
        runner.inventory_with_development())
    assert bad == []


def classification(labels):
    return [{"seed": 2000 + i // 2, "query": i % 2, "family": "f", "reference": label}
            for i, label in enumerate(labels)]


def test_selection_takes_the_first_rejected_and_accepted_queries_in_pool_order():
    labels = ["accepted", "rejected"] * 20 + ["unavailable", "failed:timeout"]
    chosen = runner.select(classification(labels))
    assert [r["reference"] for r in chosen].count("rejected") == runner.TARGET_REJECTED
    assert [r["reference"] for r in chosen].count("accepted") == runner.TARGET_ACCEPTED
    assert chosen == sorted(chosen, key=lambda r: (r["seed"], r["query"]))
    accepted_seeds = [r["seed"] for r in chosen if r["reference"] == "accepted"]
    assert accepted_seeds == list(range(2000, 2008))
    few = runner.select(classification(["rejected"] * 3 + ["accepted"] * 2))
    assert len(few) == 5


def episodes(table):
    rows = []
    for case, by_planner in table.items():
        for planner in runner.PLANNERS:
            for seed in range(3):
                rows.append({"case": case, "planner": planner,
                             "failure_class": "reached" if seed < by_planner.get(planner, 0)
                             else "driving_collision"})
    return rows


def row(reference, candidate, astar=0, hybrid=0):
    return {"astar": astar, "hybrid_astar": hybrid, runner.REFERENCE: reference,
            runner.CANDIDATE: candidate}


def decide(table, stratum, differ=None, mismatch=False, p95=300.0):
    audit = []
    for case in table:
        same = json.dumps([[0, 0, 0]])
        audit.append({"case": case, "planner": runner.REFERENCE, "matches_stored_path": True,
                      "smoothing": "accepted" if stratum[case] == "accepted" else "rejected",
                      "rescue": "", "path_digest": same})
        audit.append({"case": case, "planner": runner.CANDIDATE, "matches_stored_path": True,
                      "smoothing": "accepted" if stratum[case] == "accepted" else "rejected",
                      "rescue": "not_needed" if stratum[case] == "accepted" else "failed",
                      "path_digest": "different" if case == differ else same})
    if mismatch:
        audit[0]["matches_stored_path"] = False
    return runner.decide(episodes(table), audit, stratum, {runner.CANDIDATE: p95})


def held_out(gains):
    table = {f"a{i}": row(3, 3, astar=3 if i < 3 else 0) for i in range(8)}
    table |= {f"r{i}": row(0, 3 if i < gains else 0) for i in range(16)}
    stratum = {c: "accepted" if c.startswith("a") else "rejected" for c in table}
    return table, stratum


def test_verdicts_follow_the_registered_rule():
    table, stratum = held_out(4)
    result = decide(table, stratum)
    assert result["required_net_gain"] == 4 and result["verdict"] == "supported"
    assert result["no_regression_evidence"] == "untestable"
    assert decide(*held_out(3))["verdict"] == "not_supported"
    lost = dict(table, a0=row(3, 0, astar=3))
    assert decide(lost, stratum)["verdict"] == "not_supported"
    assert decide(table, stratum, mismatch=True)["verdict"] == "invalid_audit"
    assert decide(table, stratum, differ="a1")["verdict"] == "invalid_audit"
    few = {c: v for c, v in table.items() if c.startswith("a") or c in {"r0", "r1"}}
    assert decide(few, {c: stratum[c] for c in few})["verdict"] == "undecidable"


def test_promotion_checklist_is_reported_not_decided():
    table, stratum = held_out(8)
    checks = decide(table, stratum, p95=1400.0)["promotion_checklist"]
    assert checks["queries_at_least_24"] and not checks["astar_success_query_share_at_least_30pct"]
    assert checks["reach_rate_gain_at_least_25pp"] and not checks["planning_p95_at_most_25pct_of_timeout"]
    assert not checks["post_processing_acceptance_at_least_75pct"]


def smoke(monkeypatch):
    monkeypatch.setattr(runner.previous, "repository_state", lambda _: {
        "run_commit": "test", "tracked_tree_dirty": False, "prereg_commit": "test"})
    monkeypatch.setattr(runner, "inventory_with_development", lambda: ({}, set()))


def test_run_writes_classification_protocol_and_decision(tmp_path, monkeypatch):
    smoke(monkeypatch)
    output = tmp_path / "out"
    summary, decision = runner.run(output, "test", pool_seeds=runner.SMOKE_SEEDS)
    assert {r["planner"] for r in summary} == set(runner.PLANNERS)
    classification_rows = (output / "classification.csv").read_text(encoding="utf-8").splitlines()
    assert len(classification_rows) == 1 + 2 * len(runner.SMOKE_SEEDS)
    assert decision["verdict"] in {"undecidable", "invalid_audit"}
    assert decision["accepted_paths_identical"]
    for name in ("novelty.json", "protocol_start.json", "protocol.json", "decision.json"):
        assert (output / name).is_file()


def test_development_overlap_and_failures_are_refused_or_recorded(tmp_path, monkeypatch):
    smoke(monkeypatch)
    with pytest.raises(ValueError, match="overlaps"):
        runner.run(tmp_path / "dev", "test", pool_seeds=(runner.development.DEV_SEEDS[0],))
    monkeypatch.setattr(runner, "run_case", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        runner.run(tmp_path / "out", "test", pool_seeds=runner.SMOKE_SEEDS)
    aborted = json.loads((tmp_path / "out" / "aborted.json").read_text(encoding="utf-8"))
    assert "boom" in aborted["error"]
