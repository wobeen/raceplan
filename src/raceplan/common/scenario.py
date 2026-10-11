"""Validated experiment-scenario configuration."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from .types import Pose2D


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    map_path: Path
    start: Pose2D
    goal: Pose2D
    seed: int
    timeout_s: float


def _pose(value: Any, *, field: str) -> Pose2D:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"{field} must be [x, y, yaw]")
    return Pose2D(*(float(component) for component in value))


def load_scenario(path: str | Path) -> Scenario:
    """Load a single scenario and resolve its map path relative to the YAML."""

    scenario_path = Path(path).resolve()
    with scenario_path.open("r", encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    if not isinstance(config, dict):
        raise ValueError("scenario must contain a YAML mapping")

    required = {"name", "map", "start", "goal", "seed", "timeout_s"}
    missing = sorted(required.difference(config))
    if missing:
        raise ValueError(f"missing required scenario fields: {', '.join(missing)}")
    unknown = sorted(set(config).difference(required))
    if unknown:
        raise ValueError(f"unknown scenario fields: {', '.join(unknown)}")

    name = str(config["name"]).strip()
    if not name:
        raise ValueError("scenario name cannot be empty")
    seed = int(config["seed"])
    if seed < 0:
        raise ValueError("scenario seed cannot be negative")
    timeout_s = float(config["timeout_s"])
    if not isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("scenario timeout_s must be finite and positive")

    return Scenario(
        name=name,
        map_path=(scenario_path.parent / str(config["map"])).resolve(),
        start=_pose(config["start"], field="start"),
        goal=_pose(config["goal"], field="goal"),
        seed=seed,
        timeout_s=timeout_s,
    )

