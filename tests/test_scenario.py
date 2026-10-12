from pathlib import Path

import pytest

from raceplan.common import load_scenario


def test_loads_scenario_and_resolves_map_path(tmp_path: Path) -> None:
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(
        "\n".join(
            [
                "name: open-field-01",
                "map: ../maps/open.yaml",
                "start: [0.5, 1.5, 0.0]",
                "goal: [4.5, 3.5, 1.57]",
                "map_seed: null",
                "simulation_seed: 42",
                "timeout_s: 10.0",
            ]
        ),
        encoding="utf-8",
    )

    scenario = load_scenario(scenario_file)

    assert scenario.name == "open-field-01"
    assert scenario.map_path == (tmp_path / "../maps/open.yaml").resolve()
    assert scenario.start.x == pytest.approx(0.5)
    assert scenario.goal.yaw == pytest.approx(1.57)
    assert scenario.map_seed is None
    assert scenario.simulation_seed == 42
    assert scenario.timeout_s == pytest.approx(10.0)


def test_rejects_unknown_fields(tmp_path: Path) -> None:
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(
        "\n".join(
            [
                "name: invalid",
                "map: map.yaml",
                "start: [0, 0, 0]",
                "goal: [1, 1, 0]",
                "map_seed: 0",
                "simulation_seed: 0",
                "timeout_s: 1",
                "typo: true",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown scenario fields: typo"):
        load_scenario(scenario_file)

