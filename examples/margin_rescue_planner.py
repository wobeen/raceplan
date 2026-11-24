"""Lead-in rescue whose rescued paths must keep a margin of the observed tracking error.

Development candidate for docs/MARGIN_RESCUE_DEVELOPMENT.md.  In the previous
step (docs/LEADIN_RESCUE_DEVELOPMENT.md) every rescued path was verified with a
0.02 m footprint margin and every one collided.  Here only the rescue changes:

1. ``SmoothedLowClearance`` (margin 0.02 m) runs first.  If it accepts its path
   or fails to plan, that result is returned unchanged.
2. Otherwise the committed lead-in rescue runs with a post-processor whose
   footprint margin is ``footprint_margin_m``.  That margin applies to the
   re-run smoothing check, every lead-in arc sample, and the joined path.  The
   stricter post-processor also rejects (same smoothing, stricter check), so the
   rescue stage is always reached.  Without a verified rescue the raw A* path
   is returned, exactly as before.

The committed plugins are loaded by content hash and are not edited.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
from math import isfinite
from pathlib import Path as FilePath
import sys
from time import perf_counter

from raceplan.common import PlannerResult, PlannerStatus
from raceplan.planners.base import Planner


def _load_leadin():
    path = FilePath(__file__).resolve().with_name("leadin_rescue_planner.py")
    source = path.read_bytes()
    name = "_raceplan_leadin_" + sha256(source).hexdigest()
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        exec(compile(source, str(path), "exec"), module.__dict__)
    return sys.modules[name]


leadin = _load_leadin()
base = leadin.base


@dataclass(frozen=True)
class MarginRescueConfig:
    footprint_margin_m: float = 0.08
    reference_margin_m: float = 0.02
    target_clearance_m: float = 0.30

    def __post_init__(self):
        if not isfinite(self.footprint_margin_m) or self.footprint_margin_m < self.reference_margin_m:
            raise ValueError("footprint_margin_m must be finite and at least the reference margin")


class MarginRescue08(Planner):
    """Rescue margin 0.08 m (about the median maximum tracking error)."""

    margin = 0.08

    def __init__(self):
        self.config = MarginRescueConfig(footprint_margin_m=self.margin)
        self.reference = base.SmoothedLowClearance()
        self.rescue = leadin.LeadInRescueK3()
        self.rescue.base = base.SmoothedAStar(base.SmoothingConfig(
            target_clearance_m=self.config.target_clearance_m,
            footprint_margin_m=self.config.footprint_margin_m))

    @property
    def name(self):
        return f"margin_rescue_{round(self.margin * 100):02d}"

    def plan(self, grid, start, goal, *, timeout_s=None):
        if timeout_s is not None and (not isfinite(timeout_s) or timeout_s < 0):
            raise ValueError("timeout_s must be finite and non-negative")
        started = perf_counter()
        first = self.reference.plan(grid, start, goal, timeout_s=timeout_s)
        if first.status is not PlannerStatus.SUCCESS or first.metadata["smoothing"] == "accepted":
            rescue = "base_failed" if first.status is not PlannerStatus.SUCCESS else "not_needed"
            return PlannerResult(first.status, first.path, first.expanded_nodes,
                                 perf_counter() - started,
                                 {**first.metadata, "algorithm": self.name, "rescue": rescue})
        remaining = None if timeout_s is None else max(0.0, timeout_s - (perf_counter() - started))
        second = self.rescue.plan(grid, start, goal, timeout_s=remaining)
        if second.status is not PlannerStatus.SUCCESS:
            # Out of time before the stricter pass finished: keep the reference fallback.
            return PlannerResult(first.status, first.path, first.expanded_nodes,
                                 perf_counter() - started,
                                 {**first.metadata, "algorithm": self.name, "rescue": "timeout"})
        return PlannerResult(second.status, second.path,
                             first.expanded_nodes + second.expanded_nodes,
                             perf_counter() - started,
                             {**second.metadata, "algorithm": self.name,
                              "rescue_margin_m": self.config.footprint_margin_m})


class MarginRescue11(MarginRescue08):
    """Rescue margin 0.11 m (about the 90th percentile and maximum)."""

    margin = 0.11
