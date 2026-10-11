from pathlib import Path

from raceplan.compare import main


def test_compare_cli_reports_matching_costs(capsys) -> None:
    root = Path(__file__).resolve().parents[1]

    exit_code = main([str(root / "scenarios" / "demo.yaml")])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "dijkstra      success" in output
    assert "astar         success" in output
    assert "hybrid_astar  success" in output
    assert "optimal_cost_match=true" in output
    assert "astar_expanded_reduction=" in output
