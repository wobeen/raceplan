"""Lead-in rescue with a verification margin at least the observed tracking error.

Development candidate for docs/MARGIN_RESCUE_DEVELOPMENT.md.  The previous
step (docs/LEADIN_RESCUE_DEVELOPMENT.md) produced verified paths whose 0.02 m
footprint margin was smaller than the fixed tracker's error, and every one of
them collided.  Here the same post-processing and lead-in rescue run with a
larger footprint margin in every verification (smoothed path and lead-in arcs).
Margins were fixed from the exposed previous run before any new input existed:
reached ``smoothed_low_clearance`` episodes had maximum tracking error
median 0.076 m and 90th percentile 0.102 m (maximum 0.113 m).
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
from pathlib import Path as FilePath
import sys

from raceplan.common import PlannerResult
from raceplan.planners.base import Planner


def _load_leadin():
    """Load the committed lead-in plugin by content hash without editing it."""
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
class MarginLeadInConfig(leadin.LeadInConfig):
    footprint_margin_m: float = 0.08


def margin_smoother(margin: float):
    """``SmoothedLowClearance`` parameters with only the footprint margin changed."""
    return base.SmoothedAStar(base.SmoothingConfig(target_clearance_m=0.30,
                                                   footprint_margin_m=margin))


class MarginRescue08(leadin.LeadInRescueK3):
    """Margin 0.08 m (about the median maximum tracking error) plus lead-in rescue."""

    margin = 0.08

    def __init__(self):
        super().__init__(MarginLeadInConfig(footprint_margin_m=self.margin))
        self.base = margin_smoother(self.margin)

    @property
    def name(self):
        return f"margin_rescue_{round(self.margin * 100):02d}"


class MarginRescue11(MarginRescue08):
    """Margin 0.11 m (about the 90th percentile and maximum) plus lead-in rescue."""

    margin = 0.11


class MarginOnly08(Planner):
    """Ablation: margin 0.08 m post-processing without lead-in rescue; not selectable."""

    def __init__(self):
        self.base = margin_smoother(0.08)
        self.config = self.base.config

    @property
    def name(self):
        return "margin_only_08"

    def plan(self, grid, start, goal, *, timeout_s=None):
        result = self.base.plan(grid, start, goal, timeout_s=timeout_s)
        return PlannerResult(result.status, result.path, result.expanded_nodes,
                             result.planning_time_s, {**result.metadata, "algorithm": self.name})
