from pathlib import Path

import pytest

from raceplan.common import load_occupancy_map


def _write_map(tmp_path: Path, *, origin_yaw: float = 0.0) -> Path:
    # Top image row: occupied, free. Bottom row: unknown, free.
    (tmp_path / "map.pgm").write_text(
        "P2\n2 2\n255\n0 255\n128 255\n",
        encoding="ascii",
    )
    config = tmp_path / "map.yaml"
    config.write_text(
        "\n".join(
            [
                "image: map.pgm",
                "resolution: 0.25",
                f"origin: [-1.0, 2.0, {origin_yaw}]",
                "negate: 0",
                "occupied_thresh: 0.65",
                "free_thresh: 0.196",
                "source: synthetic-test-fixture",
                "license: CC0-1.0",
            ]
        ),
        encoding="utf-8",
    )
    return config


def test_loads_ros_style_map_and_flips_image_rows(tmp_path: Path) -> None:
    metadata = load_occupancy_map(_write_map(tmp_path))

    assert metadata.grid.resolution == pytest.approx(0.25)
    assert metadata.grid.origin_x == pytest.approx(-1.0)
    assert metadata.grid.origin_y == pytest.approx(2.0)
    assert metadata.source == "synthetic-test-fixture"
    assert metadata.license == "CC0-1.0"
    assert metadata.grid.occupied.tolist() == [[True, False], [True, False]]


def test_unknown_cells_can_be_treated_as_free(tmp_path: Path) -> None:
    metadata = load_occupancy_map(
        _write_map(tmp_path),
        unknown_as_occupied=False,
    )

    assert metadata.grid.occupied.tolist() == [[False, False], [True, False]]


def test_rejects_rotated_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="rotated"):
        load_occupancy_map(_write_map(tmp_path, origin_yaw=0.1))

