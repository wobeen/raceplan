"""Shared geometry, grids, and data contracts."""

from .grid import OccupancyGrid
from .inflation import inflate_obstacles
from .map_io import MapMetadata, load_occupancy_map
from .scenario import Scenario, load_scenario
from .types import Path, PlannerResult, PlannerStatus, Pose2D
from .vehicle import VehicleGeometry, footprint_corners, footprint_in_collision

__all__ = [
    "MapMetadata",
    "OccupancyGrid",
    "Path",
    "PlannerResult",
    "PlannerStatus",
    "Pose2D",
    "Scenario",
    "VehicleGeometry",
    "footprint_corners",
    "footprint_in_collision",
    "inflate_obstacles",
    "load_occupancy_map",
    "load_scenario",
]

