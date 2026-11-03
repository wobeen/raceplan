"""Timed plan calls and data-contract validation for the development runner."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from numbers import Integral, Real
from time import perf_counter

from raceplan.common import Path, PlannerResult, PlannerStatus, Pose2D

ERROR_TYPE_LIMIT = 128
ERROR_MESSAGE_LIMIT = 4096
TRUNCATION_MARKER = '... [truncated]'


def _number(value, location, *, non_negative=False):
    if isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value):
        raise ValueError(f'{location} must be a finite real number')
    if non_negative and value < 0:
        raise ValueError(f'{location} must be non-negative')
    return float(value)


def validate_result(result):
    """Validate values, not safety or optimality; snapshot mutable path sequences."""
    if not isinstance(result, PlannerResult):
        raise TypeError('plan must return raceplan.common.PlannerResult')
    if not isinstance(result.status, PlannerStatus):
        raise TypeError('result.status must be PlannerStatus')
    if (isinstance(result.expanded_nodes, bool) or not isinstance(result.expanded_nodes, Integral)
            or result.expanded_nodes < 0):
        raise ValueError('result.expanded_nodes must be a non-negative integer')
    reported_time = _number(result.planning_time_s, 'result.planning_time_s', non_negative=True)
    if not isfinite(reported_time * 1000.0):
        raise ValueError('result.planning_time_s must convert to finite milliseconds')
    if not isinstance(result.metadata, Mapping):
        raise TypeError('result.metadata must be a mapping')
    path = None
    if result.status is PlannerStatus.SUCCESS:
        if not isinstance(result.path, Path):
            raise TypeError('successful result.path must be raceplan.common.Path')
        if (not isinstance(result.path.poses, Sequence) or isinstance(result.path.poses, (str, bytes))
                or not result.path.poses):
            raise TypeError('path.poses must be a non-empty sequence of Pose2D')
        cost = _number(result.path.cost, 'path.cost', non_negative=True)
        poses = []
        for index, pose in enumerate(result.path.poses):
            if not isinstance(pose, Pose2D):
                raise TypeError(f'path.poses[{index}] must be Pose2D')
            poses.append(Pose2D(*(_number(getattr(pose, field), f'path.poses[{index}].{field}')
                                  for field in ('x', 'y', 'yaw'))))
        path = Path(tuple(poses), cost)
    elif result.path is not None:
        raise ValueError('failed planning result cannot contain a path')
    return PlannerResult(result.status, path, int(result.expanded_nodes), reported_time, dict(result.metadata))


@dataclass(frozen=True)
class PlanningOutcome:
    result: PlannerResult
    runner_planning_time_ms: float
    error_type: str = ''
    error_message: str = ''
    reported_time_available: bool = True
    error_truncated: bool = False


def _diagnostic(text, limit):
    truncated = len(text) > limit
    if truncated:
        text = text[:limit - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
    return text.encode('utf-8', errors='replace').decode('utf-8'), truncated


def _failure(exc, elapsed_ms):
    try:
        message = str(exc)
    except Exception:
        message = '<exception message unavailable>'
    # Bound new CSV fields below csv's default limit; preserve short message text.
    message, message_truncated = _diagnostic(message, ERROR_MESSAGE_LIMIT)
    error_type, type_truncated = _diagnostic(type(exc).__name__, ERROR_TYPE_LIMIT)
    return PlanningOutcome(PlannerResult(PlannerStatus.ERROR), elapsed_ms, error_type, message,
                           reported_time_available=False,
                           error_truncated=message_truncated or type_truncated)


def plan_once(planner, grid, start, goal, *, timeout_s, is_custom):
    """Time only plan(); custom call/contract errors continue, builtin bugs propagate."""
    started = perf_counter()
    try:
        raw = planner.plan(grid, start, goal, timeout_s=timeout_s)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000.0
        if not is_custom:
            raise
        return _failure(exc, elapsed_ms)
    elapsed_ms = (perf_counter() - started) * 1000.0
    try:
        result = validate_result(raw)
    except Exception as exc:
        if not is_custom:
            raise
        return _failure(exc, elapsed_ms)
    if result.status is PlannerStatus.ERROR:
        return PlanningOutcome(result, elapsed_ms, 'PlannerReportedError', 'planner returned planning_error')
    return PlanningOutcome(result, elapsed_ms)
