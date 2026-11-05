"""Compare sharp-turn cost variants on the already exposed 2026-11-03 validation split.

This is development selection, not held-out evaluation.  It deliberately reads
only the committed ``inputs/validation`` scenarios from the prior turn-aware
study and never opens its evaluation inputs.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
from time import perf_counter

from raceplan.analyze import main as analyze
from raceplan.experiment import main as experiment

ROOT = Path(__file__).resolve().parents[1]
INPUT_ROOT = ROOT / "results/analysis/turn_aware_holdout_20261103/inputs/validation"
PLUGIN = ROOT / "examples/sharp_turn_planner.py"
FAMILIES = ("offset_islands", "staggered_windows")
CLASSES = ("SharpTurnLow", "SharpTurnAStar", "SharpTurnHigh", "SharpTurnCombined")
PLANNERS = ("astar", "sharp_turn_low", "sharp_turn_astar",
            "sharp_turn_high", "sharp_turn_combined")
SEEDS = (11, 12, 13)
NOISE = {
    "initial-position-std-m": 0.02,
    "initial-yaw-std-rad": 0.02,
    "steering-std-rad": 0.01,
    "speed-measurement-std-mps": 0.02,
}


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows):
    with path.open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def optional_median(rows, field):
    values = [float(row[field]) for row in rows if row.get(field) not in (None, "")]
    return median(values) if values else None


def run(output: Path):
    if output.exists():
        raise ValueError("output directory already exists")
    output.mkdir(parents=True)
    started = perf_counter()
    episodes, pairs, plans = [], [], []
    inputs = []
    for family in FAMILIES:
        for query in range(2):
            scenario = INPUT_ROOT / family / f"q{query}.yaml"
            inputs.append(scenario)
            case = f"{family}_q{query}"
            target = output / "batches" / case
            target.mkdir(parents=True)
            summary = target / "comparison.csv"
            command = [str(scenario), "--output", str(summary),
                       "--planners", "astar", "--simulation-seeds", *map(str, SEEDS)]
            for classname in CLASSES:
                command += ["--custom-planner", f"{PLUGIN}:{classname}"]
            for setting, value in NOISE.items():
                command += ["--" + setting, str(value)]
            experiment(command)
            analysis = target / "analysis"
            analyze([str(summary), "--baseline", "astar", "--output-dir", str(analysis)])
            local = read_csv(analysis / "episodes.csv")
            episodes += [dict(case=case, family=family, query=query, **row) for row in local]
            pairs += [dict(case=case, family=family, query=query, **row)
                      for row in read_csv(analysis / "paired.csv")]
            for row in local:
                if int(row["simulation_seed"]) == SEEDS[0]:
                    plans.append(dict(case=case, family=family, query=query, **row))

    summary_rows = []
    for planner in PLANNERS:
        rows = [row for row in episodes if row["planner"] == planner]
        successes = [row for row in rows if row["failure_class"] == "reached"]
        counts = Counter(row["failure_class"] for row in rows)
        plan_rows = [row for row in plans if row["planner"] == planner]
        summary_rows.append({
            "planner": planner,
            "episodes": len(rows),
            "reached": len(successes),
            "collisions": counts["driving_collision"] + counts["initial_collision"],
            "timeouts": counts["timeout"],
            "planning_failures": sum(value for key, value in counts.items()
                                     if key.startswith("planning_")),
            "success_tracking_rmse_m_median": optional_median(successes, "tracking_rmse_m"),
            "success_completion_time_s_median": optional_median(successes, "completion_time_s"),
            "all_driven_clearance_m_median": optional_median(rows, "driving_min_sampled_clearance_m"),
            "path_total_absolute_turn_rad_median": optional_median(plan_rows, "total_absolute_turn_rad"),
            "path_max_discrete_curvature_per_m_median": optional_median(
                plan_rows, "max_discrete_curvature_per_m"),
            "planning_time_ms_median": optional_median(plan_rows, "planning_time_ms"),
            "expanded_nodes_median": optional_median(plan_rows, "expanded_nodes"),
        })

    paired_rows = []
    for planner in PLANNERS[1:]:
        rows = [row for row in pairs if row["planner"] == planner]
        paired_rows.append({
            "planner": planner,
            "baseline": "astar",
            "pairs": len(rows),
            "reach_wins": sum(row["planner_outcome"] == "reached"
                              and row["baseline_outcome"] != "reached" for row in rows),
            "reach_losses": sum(row["planner_outcome"] != "reached"
                                and row["baseline_outcome"] == "reached" for row in rows),
            "both_reached": sum(row["both_reached"] == "True" for row in rows),
            "delta_tracking_rmse_m_median": optional_median(rows, "delta_tracking_rmse_m"),
            "delta_completion_time_s_median": optional_median(rows, "delta_completion_time_s"),
            "delta_driving_clearance_m_median": optional_median(
                rows, "delta_driving_min_sampled_clearance_m"),
        })

    write_csv(output / "summary.csv", summary_rows)
    write_csv(output / "paired.csv", paired_rows)
    protocol = {
        "kind": "development_selection_not_held_out_evaluation",
        "source_split": "turn_aware_holdout_20261103/validation only",
        "families": list(FAMILIES), "queries_per_family": 2,
        "seeds": list(SEEDS), "planners": list(PLANNERS), "noise": NOISE,
        "episodes": len(episodes), "wall_time_s": perf_counter() - started,
        "source_sha256": {
            str(PLUGIN.relative_to(ROOT)): digest(PLUGIN),
            str(Path(__file__).resolve().relative_to(ROOT)): digest(Path(__file__).resolve()),
        },
        "input_sha256": {str(path.relative_to(ROOT)): digest(path) for path in inputs},
        "selection_rule": (
            "prefer no reach-rate regression vs A*; then lower median successful RMSE and "
            "max discrete curvature; evaluation remains unused"
        ),
    }
    (output / "protocol.json").write_text(
        json.dumps(protocol, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return summary_rows, paired_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary, paired = run(args.output_dir.resolve())
    print(json.dumps({"summary": summary, "paired": paired}, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
