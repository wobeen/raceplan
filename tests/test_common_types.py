import pytest

from raceplan.common import Path, PlannerResult, PlannerStatus, Pose2D


def test_success_requires_path() -> None:
    with pytest.raises(ValueError, match="requires a path"):
        PlannerResult(status=PlannerStatus.SUCCESS)


def test_failure_rejects_path() -> None:
    path = Path((Pose2D(0.0, 0.0),), cost=0.0)
    with pytest.raises(ValueError, match="cannot contain"):
        PlannerResult(status=PlannerStatus.NO_PATH, path=path)


def test_pose_rejects_non_finite_value() -> None:
    with pytest.raises(ValueError, match="finite"):
        Pose2D(float("nan"), 0.0)

