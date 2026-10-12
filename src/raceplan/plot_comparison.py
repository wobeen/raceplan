"""Render the current three-planner development comparison as a PNG."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from raceplan.common import load_occupancy_map, load_scenario
from raceplan.compare import _baseline_hybrid_astar
from raceplan.planners import AStarPlanner, DijkstraPlanner


COLORS = {
    "dijkstra": "#2563EB",
    "astar": "#EA580C",
    "hybrid_astar": "#16A34A",
}
LABELS = {
    "dijkstra": "Dijkstra",
    "astar": "A*",
    "hybrid_astar": "Hybrid A*",
}


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    points: list[tuple[float, float]],
    *,
    fill: str,
    width: int,
) -> None:
    for index, (start, end) in enumerate(zip(points, points[1:])):
        if index % 2 == 0:
            draw.line((start, end), fill=fill, width=width)


def render_comparison(scenario_path: Path, output_path: Path) -> Path:
    scenario = load_scenario(scenario_path)
    metadata = load_occupancy_map(scenario.map_path)
    planners = (DijkstraPlanner(), AStarPlanner(), _baseline_hybrid_astar())
    results = {
        planner.name: planner.plan(
            metadata.grid,
            scenario.start,
            scenario.goal,
            timeout_s=scenario.timeout_s,
        )
        for planner in planners
    }

    canvas = Image.new("RGB", (1500, 880), "#F8FAFC")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(34, bold=True)
    heading_font = _font(23, bold=True)
    body_font = _font(18)
    small_font = _font(15)

    draw.text((55, 34), "RacePlan Planner Comparison", fill="#0F172A", font=title_font)
    draw.text(
        (55, 80),
        f"Scenario: {scenario.name}  |  Development run",
        fill="#64748B",
        font=body_font,
    )

    grid = metadata.grid
    map_left, map_top = 75, 145
    cell = min(70, 780 // grid.width, 600 // grid.height)
    map_width, map_height = grid.width * cell, grid.height * cell
    draw.rectangle(
        (map_left, map_top, map_left + map_width, map_top + map_height),
        fill="#FFFFFF",
        outline="#94A3B8",
        width=2,
    )
    for row in range(grid.height):
        for column in range(grid.width):
            left = map_left + column * cell
            top = map_top + (grid.height - 1 - row) * cell
            if grid.occupied[row, column]:
                draw.rectangle((left, top, left + cell, top + cell), fill="#CBD5E1")
            draw.rectangle((left, top, left + cell, top + cell), outline="#E2E8F0", width=1)

    def map_point(x: float, y: float) -> tuple[float, float]:
        return (
            map_left + (x - grid.origin_x) / grid.resolution * cell,
            map_top + map_height - (y - grid.origin_y) / grid.resolution * cell,
        )

    for name, result in results.items():
        if result.path is None:
            continue
        points = [map_point(pose.x, pose.y) for pose in result.path.poses]
        if name == "astar":
            _draw_dashed_line(draw, points, fill=COLORS[name], width=5)
        else:
            draw.line(points, fill=COLORS[name], width=6 if name == "hybrid_astar" else 5, joint="curve")

    start = map_point(scenario.start.x, scenario.start.y)
    goal = map_point(scenario.goal.x, scenario.goal.y)
    draw.ellipse((start[0] - 9, start[1] - 9, start[0] + 9, start[1] + 9), fill="#22C55E", outline="#FFFFFF", width=3)
    draw.ellipse((goal[0] - 10, goal[1] - 10, goal[0] + 10, goal[1] + 10), fill="#EF4444", outline="#FFFFFF", width=3)
    draw.text((start[0] + 13, start[1] - 10), "Start", fill="#0F172A", font=small_font)
    draw.text((goal[0] - 58, goal[1] - 34), "Goal", fill="#0F172A", font=small_font)

    legend_y = map_top + map_height + 28
    legend_x = map_left
    for name in ("dijkstra", "astar", "hybrid_astar"):
        draw.line((legend_x, legend_y + 10, legend_x + 34, legend_y + 10), fill=COLORS[name], width=5)
        draw.text((legend_x + 44, legend_y), LABELS[name], fill="#0F172A", font=body_font)
        legend_x += 190

    panel_left = 930
    draw.text((panel_left, 145), "Result metrics", fill="#0F172A", font=heading_font)
    metrics = (
        ("Path cost", "cost", "m", 3),
        ("Expanded nodes", "expanded", "", 0),
        ("Planning time", "time", "ms", 3),
    )
    panel_y = 195
    for title, key, unit, digits in metrics:
        values = {}
        for name, result in results.items():
            if key == "cost":
                values[name] = result.path.cost if result.path else 0.0
            elif key == "expanded":
                values[name] = float(result.expanded_nodes)
            else:
                values[name] = result.planning_time_s * 1000
        maximum = max(values.values()) or 1.0
        draw.text((panel_left, panel_y), title, fill="#334155", font=body_font)
        panel_y += 38
        for name in ("dijkstra", "astar", "hybrid_astar"):
            value = values[name]
            draw.text((panel_left, panel_y), LABELS[name], fill="#475569", font=small_font)
            bar_left, bar_right = panel_left + 110, 1380
            draw.rectangle((bar_left, panel_y + 3, bar_right, panel_y + 18), fill="#E2E8F0")
            draw.rectangle(
                (bar_left, panel_y + 3, bar_left + (bar_right - bar_left) * value / maximum, panel_y + 18),
                fill=COLORS[name],
            )
            value_text = f"{value:.{digits}f}{(' ' + unit) if unit else ''}"
            draw.text((1390, panel_y - 2), value_text, fill="#0F172A", font=small_font, anchor="ra")
            panel_y += 31
        panel_y += 28

    draw.text(
        (930, 760),
        "Hybrid A* stops within 0.5 m of the goal.",
        fill="#64748B",
        font=small_font,
    )
    draw.text(
        (930, 785),
        "Timing is illustrative, not an official benchmark.",
        fill="#64748B",
        font=small_font,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG")
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/figures/planner_comparison.png"))
    args = parser.parse_args(argv)
    print(render_comparison(args.scenario, args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
