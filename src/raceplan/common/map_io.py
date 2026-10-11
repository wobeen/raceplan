"""Portable ROS-style occupancy-map loading."""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

from .grid import OccupancyGrid


@dataclass(frozen=True, slots=True)
class MapMetadata:
    """Loaded map plus provenance required for research publication."""

    grid: OccupancyGrid
    yaml_path: Path
    image_path: Path
    source: str
    license: str


def _mapping(value: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must contain a YAML mapping")
    return value


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required map field: {key}")
    return mapping[key]


def load_occupancy_map(
    yaml_path: str | Path,
    *,
    unknown_as_occupied: bool = True,
) -> MapMetadata:
    """Load a grayscale image using ROS map-server threshold semantics.

    Image row zero is at the top, while :class:`OccupancyGrid` row zero is at
    the bottom, so the loaded image is flipped vertically. Rotated map origins
    are rejected until all planners support them consistently.
    """

    config_path = Path(yaml_path).resolve()
    with config_path.open("r", encoding="utf-8") as stream:
        config = _mapping(yaml.safe_load(stream), context=str(config_path))

    image_path = (config_path.parent / str(_required(config, "image"))).resolve()
    resolution = float(_required(config, "resolution"))
    origin = _required(config, "origin")
    if not isinstance(origin, list) or len(origin) != 3:
        raise ValueError("map origin must be [x, y, yaw]")
    origin_x, origin_y, origin_yaw = (float(value) for value in origin)
    if not isclose(origin_yaw, 0.0, abs_tol=1e-12):
        raise ValueError("rotated map origins are not supported")

    occupied_threshold = float(config.get("occupied_thresh", 0.65))
    free_threshold = float(config.get("free_thresh", 0.196))
    if not 0.0 <= free_threshold < occupied_threshold <= 1.0:
        raise ValueError("thresholds must satisfy 0 <= free < occupied <= 1")

    source = str(_required(config, "source")).strip()
    license_name = str(_required(config, "license")).strip()
    if not source or not license_name:
        raise ValueError("map source and license cannot be empty")

    with Image.open(image_path) as image:
        grayscale = np.asarray(image.convert("L"), dtype=np.float64)
    normalized = grayscale / 255.0
    occupancy_probability = normalized if bool(config.get("negate", 0)) else 1.0 - normalized
    occupied = occupancy_probability >= occupied_threshold
    if unknown_as_occupied:
        occupied |= occupancy_probability > free_threshold
    occupied = np.flipud(occupied)

    return MapMetadata(
        grid=OccupancyGrid(occupied, resolution, origin_x, origin_y),
        yaml_path=config_path,
        image_path=image_path,
        source=source,
        license=license_name,
    )

