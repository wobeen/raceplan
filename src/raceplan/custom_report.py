"""Render a saved experiment without replanning or rerunning the simulation."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from math import hypot
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont

from raceplan.common import Pose2D, load_occupancy_map


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _font(size: int):
    for filename in ('C:/Windows/Fonts/malgun.ttf', 'C:/Windows/Fonts/segoeui.ttf', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(filename, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _number(value: str) -> str:
    return f'{float(value):.3f}' if value else '-'


def _fit_line(draw, text, font, width):
    """Display one line and use logarithmically many width measurements."""
    text = ''.join(' ' if unicodedata.category(char).startswith('C') else char for char in text)
    text = ' '.join(text.split())
    if draw.textlength(text, font=font) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if draw.textlength(text[:middle] + '...', font=font) <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low] + '...'


def render_report(summary: Path, output: Path, seed: int | None = None) -> Path:
    """Show all-seed outcomes and one seed's paths, using recorded map provenance."""
    summary, output = summary.resolve(), output.resolve()
    if output.exists():
        raise ValueError('output already exists; choose a new filename')
    manifest_path = summary.with_name(summary.stem + '_manifest.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('status') != 'complete':
        raise ValueError('a completed schema-version 1 batch is required')
    if manifest['artifacts']['summary'] != summary.name:
        raise ValueError('summary does not match its manifest')

    def artifact(key: str) -> Path:
        name = manifest['artifacts'][key]
        if Path(name).name != name:
            raise ValueError('artifact must be a sibling filename')
        return summary.with_name(name)

    map_path = Path(manifest['scenario']['map_path'])
    if _hash(map_path) != manifest['map_yaml_sha256']:
        raise ValueError('map YAML changed since the batch')
    metadata = load_occupancy_map(map_path)
    if _hash(metadata.image_path) != manifest['map_image_sha256']:
        raise ValueError('map image changed since the batch')
    grid = metadata.grid
    start = Pose2D(**manifest['scenario']['start'])
    goal = Pose2D(**manifest['scenario']['goal'])
    rows = _read(summary)
    expected = {(name, str(s)) for name in manifest['planners'] for s in manifest['simulation_seeds']}
    pairs = [(row['planner'], row['simulation_seed']) for row in rows]
    if not rows or len(set(pairs)) != len(pairs) or set(pairs) != expected:
        raise ValueError('summary planner/seed coverage does not match manifest')
    if len({row['episode_id'] for row in rows}) != len(rows):
        raise ValueError('duplicate episode IDs')
    seed = manifest['simulation_seeds'][0] if seed is None else seed
    if seed not in manifest['simulation_seeds']:
        raise ValueError(f'seed {seed} is absent from this batch')
    paths, traces = defaultdict(list), defaultdict(list)
    for waypoint in _read(artifact('paths')):
        paths[waypoint['plan_id']].append(waypoint)
    for sample in _read(artifact('trajectory')):
        traces[sample['episode_id']].append(sample)
    selected = {row['planner']: row for row in rows if row['simulation_seed'] == str(seed)}
    for row in rows:
        if row['planning_status'] == 'success' and not paths[row['plan_id']]:
            raise ValueError('successful plan has no saved waypoints')
        if row['planning_status'] == 'success' and not traces[row['episode_id']]:
            raise ValueError('driven episode has no saved trajectory')
    for points, index in ((paths, 'waypoint'), (traces, 'step')):
        for values in points.values():
            values.sort(key=lambda value: int(value[index]))
            if [int(value[index]) for value in values] != list(range(len(values))):
                raise ValueError(f'{index} indices must be unique and contiguous')

    panel_h = 370
    canvas = Image.new('RGB', (1200, 125 + panel_h * len(selected)), '#f7f9fc')
    draw = ImageDraw.Draw(canvas)
    font, small, title = _font(18), _font(16), _font(26)
    heading = _fit_line(draw, f'RacePlan | {manifest["scenario"]["name"]} | seed {seed}', title, 1150)
    draw.text((24, 17), heading, fill='#14253d', font=title)
    draw.text((24, 56), f'All-seed counts: {len(manifest["simulation_seeds"])} paired seeds per planner; one plan reused.',
              fill='#526279', font=small)
    draw.text((24, 81), 'Development run | physical map shown | planning and driving use recorded inflation.',
              fill='#526279', font=small)
    cell = min(340 / grid.width, 300 / grid.height)
    for i, planner in enumerate(manifest['planners']):
        row = selected[planner]
        left, top = 25, 125 + i * panel_h
        draw.rectangle((left, top, left + grid.width * cell, top + grid.height * cell),
                       fill='white', outline='#95a2b2')
        for y, x in zip(*grid.occupied.nonzero()):
            x0, y0 = left + x * cell, top + (grid.height - 1 - y) * cell
            draw.rectangle((x0, y0, x0 + cell, y0 + cell), fill='#7a8696')

        def point(x, y):
            return (left + (float(x) - grid.origin_x) / grid.resolution * cell,
                    top + (grid.height - (float(y) - grid.origin_y) / grid.resolution) * cell)

        # Clip drawing to the map so out-of-map failures cannot cover metrics.
        map_image = Image.new('RGBA', (max(1, int(grid.width * cell) + 1), max(1, int(grid.height * cell) + 1)))
        map_draw = ImageDraw.Draw(map_image)
        for values, color in ((paths[row['plan_id']], '#9aa8b8'), (traces[row['episode_id']], '#168777')):
            points = [(x - left, y - top) for x, y in (point(p['x_m'], p['y_m']) for p in values)]
            if len(points) > 1:
                map_draw.line(points, fill=color, width=3)
            elif points:
                x, y = points[0]
                map_draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
        for pose, color in ((start, '#15803d'), (goal, '#e11d48')):
            x, y = point(pose.x, pose.y)
            x, y = x - left, y - top
            map_draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
        canvas.paste(map_image, (left, top), map_image)
        group = [r for r in rows if r['planner'] == planner]
        reached = sum(r['reached'] == 'True' and r['collision'] == 'False' for r in group)
        collisions = sum(r['collision'] == 'True' for r in group)
        timeouts = sum(r['simulation_status'] == 'timeout' for r in group)
        failures = sum(r['planning_status'] != 'success' for r in group)
        errors = sum(r['planning_status'] == 'planning_error' for r in group)
        runner_time = row.get('runner_planning_time_ms', '')
        runner_label = _number(runner_time) + ' ms' if runner_time else 'n/a'
        waypoints = paths[row['plan_id']]
        length = sum(hypot(float(b['x_m']) - float(a['x_m']), float(b['y_m']) - float(a['y_m']))
                     for a, b in zip(waypoints, waypoints[1:])) if waypoints else None
        lines = [
            planner,
            f'All seeds: reached {reached}/{len(group)} | collision {collisions} | timeout {timeouts} | plan fail {failures} / errors {errors}',
            f'Seed {seed}: plan {row["planning_status"]} | drive {row["simulation_status"]}',
            f'Planner cost: {_number(row["path_cost_m"])} | XY path length: {length:.3f} m' if length is not None else 'No planned path',
            f'Planning: reported {_number(row["planning_time_ms"])} ms | runner wall {runner_label} | expanded: {row["expanded_nodes"]}',
            f'Elapsed: {_number(row["completion_time_s"])} s | goal distance: {_number(row["goal_distance_m"])} m',
            (f'Error: {row.get("planning_error_type", "")} | {row.get("planning_error_message", "")}'
             if row['planning_status'] == 'planning_error'
             else f'Tracking RMSE: {_number(row["tracking_rmse_m"])} m'),
            'Grey: plan | teal: driven | green/red dots: start/goal',
            'Planner cost units depend on the algorithm; elapsed includes failed driving.',
        ]
        for n, line in enumerate(lines):
            line = _fit_line(draw, line, font, 755)
            draw.text((405, top + 8 + n * 31), line, fill='#14253d', font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        canvas.save(stream, format='PNG')
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('summary', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--seed', type=int, help='recorded seed to draw; defaults to the first seed')
    args = parser.parse_args(argv)
    try:
        output = render_report(args.summary, args.output, args.seed)
    except (ValueError, KeyError, OSError) as exc:
        parser.error(str(exc))
    print(f'image={output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
