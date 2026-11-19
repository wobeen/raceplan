"""Build a portable static HTML report from saved workflow or suite results."""
from __future__ import annotations

import argparse
from collections import defaultdict
import csv
from hashlib import sha256
from html import escape
from io import StringIO
import json
from math import isfinite
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from raceplan.analyze import failure_class
from raceplan.common import load_occupancy_map
from raceplan.custom_report import _fit_line, _font


class Reader:
    def __init__(self):
        self.hashes = {}

    def data(self, path):
        path = path.resolve()
        data = path.read_bytes()
        self.hashes[str(path)] = sha256(data).hexdigest()
        return data

    def json(self, path):
        return json.loads(self.data(path).decode('utf-8-sig'))

    def csv(self, path):
        return list(csv.DictReader(StringIO(self.data(path).decode('utf-8-sig'), newline='')))


def _validate_pairs(pairs, episodes, baseline, traces):
    by_key = {(row['planner'], row['simulation_seed']): row for row in episodes}
    if baseline not in {row['planner'] for row in episodes}:
        raise ValueError('saved analysis baseline is absent from this batch')
    expected = {key for key in by_key if key[0] != baseline}
    observed = [(row['planner'], row['simulation_seed']) for row in pairs]
    if set(observed) != expected or len(observed) != len(expected):
        raise ValueError('saved paired coverage mismatch')
    for pair, key in zip(pairs, observed):
        row, reference = by_key[key], by_key[(baseline, key[1])]
        both_reached = row['failure_class'] == reference['failure_class'] == 'reached'
        both_driven = bool(traces[row['episode_id']] and traces[reference['episode_id']])
        fields = {'baseline': baseline, 'planner_outcome': row['failure_class'],
                  'baseline_outcome': reference['failure_class'], 'both_reached': str(both_reached),
                  'both_driven': str(both_driven)}
        for field, value in fields.items():
            if pair[field] != value:
                raise ValueError(f'saved paired {field} differs from its episodes: {key}')
        for metric, eligible in (('tracking_rmse_m', both_reached), ('completion_time_s', both_reached),
                                 ('steering_saturation_fraction', both_reached),
                                 ('driving_min_sampled_clearance_m', both_driven)):
            field = 'delta_' + metric
            saved = pair[field]
            if eligible:
                difference = float(row[metric] or 'nan') - float(reference[metric] or 'nan')
                matches = isfinite(difference) and float(saved or 'nan') == difference
            else:
                matches = saved == ''
            if not matches:
                raise ValueError(f'saved paired {field} differs from its episodes: {key}')


def _case(reader, folder, identity, workflow_state=None):
    manifest_path = folder / 'comparison_manifest.json'
    manifest = reader.json(manifest_path)
    if manifest.get('schema_version') != 1 or manifest.get('status') != 'complete':
        raise ValueError('representatives require a completed saved batch')
    artifacts = {}
    for key in ('summary', 'paths', 'trajectory'):
        name = manifest['artifacts'][key]
        if Path(name).name != name:
            raise ValueError('saved artifact must be a sibling filename')
        artifacts[key] = folder / name
    raw = {key: reader.csv(path) for key, path in artifacts.items()}
    analysis = reader.json(folder / 'analysis/analysis.json')
    expected_hashes = {Path(name).name: value for name, value in analysis['input_sha256'].items()}
    for path in (manifest_path, *artifacts.values()):
        if expected_hashes.get(path.name) != reader.hashes[str(path.resolve())]:
            raise ValueError(f'stale analysis input hash: {path.name}')
    metadata = load_occupancy_map(Path(manifest['scenario']['map_path']))
    for path, key in ((metadata.yaml_path, 'map_yaml_sha256'), (metadata.image_path, 'map_image_sha256')):
        if sha256(reader.data(path)).hexdigest() != manifest[key]:
            raise ValueError(f'map input hash changed: {path.name}')
    episodes = reader.csv(folder / 'analysis/episodes.csv')
    expected = {(name, str(seed)) for name in manifest['planners'] for seed in manifest['simulation_seeds']}
    observed = [(row['planner'], row['simulation_seed']) for row in episodes]
    if set(observed) != expected or len(observed) != len(expected):
        raise ValueError('saved analysis episode coverage mismatch')
    # The derived episode file must agree with both the raw fields and their classification.
    originals = {row['episode_id']: row for row in raw['summary']}
    for row in episodes:
        original = originals.get(row['episode_id'])
        if original is None or any(row.get(key) != value for key, value in original.items()):
            raise ValueError('saved analysis episode differs from its summary')
        if row['failure_class'] != failure_class(original):
            raise ValueError('saved analysis failure_class differs from its summary')
        row['case_id'] = identity
    if workflow_state is None and (folder / 'workflow.json').exists():
        workflow_state = reader.json(folder / 'workflow.json')
    baseline = analysis['baseline']
    if workflow_state and workflow_state.get('baseline', baseline) != baseline:
        raise ValueError('saved analysis baseline differs from its workflow')
    pairs_path = folder / 'analysis/paired.csv'
    pairs = reader.csv(pairs_path) if pairs_path.exists() else []
    paths, traces = defaultdict(list), defaultdict(list)
    for row in raw['paths']:
        paths[row['plan_id']].append(row)
    for row in raw['trajectory']:
        traces[row['episode_id']].append(row)
    for groups, index in ((paths, 'waypoint'), (traces, 'step')):
        for rows in groups.values():
            rows.sort(key=lambda row: int(row[index]))
            if [int(row[index]) for row in rows] != list(range(len(rows))):
                raise ValueError('saved path/trajectory indices must be contiguous')
    for row in episodes:
        samples = traces[row['episode_id']]
        if row['planning_status'] == 'success' and (not paths[row['plan_id']] or not samples):
            raise ValueError('successful planning episode has missing paths/trajectory')
        if row['planning_status'] != 'success' and samples:
            raise ValueError('planning failure must have no driven trajectory')
    _validate_pairs(pairs, episodes, baseline, traces)
    return {'id': identity, 'manifest': manifest, 'grid': metadata.grid, 'episodes': episodes,
            'pairs': pairs, 'paths': paths, 'traces': traces, 'baseline': baseline}


def _load(reader, source):
    cases, coverage = [], []
    if (source / 'suite.json').exists():
        state = reader.json(source / 'suite.json')
        for identity, record in state['cases'].items():
            if Path(identity).name != identity or identity in {'.', '..'}:
                raise ValueError('invalid saved case id')
            if record['status'] == 'complete':
                case = _case(reader, source / 'cases' / identity, identity)
                if len(case['episodes']) != record['included_episode_count']:
                    raise ValueError('suite included coverage differs from saved case')
                cases.append(case)
            coverage.append(dict(record))
    else:
        workflow_path = source / 'workflow.json'
        state = reader.json(workflow_path) if workflow_path.exists() else {'status': 'complete'}
        if state['status'] == 'complete':
            case = _case(reader, source, 'batch', state)
            cases.append(case)
            count = len(case['episodes'])
            coverage.append({'case_id': 'batch', 'status': 'complete', 'expected_episode_count': count,
                             'raw_episode_count': count, 'included_episode_count': count})
        else:
            manifest_path = source / 'comparison_manifest.json'
            count = None
            if manifest_path.exists():
                manifest = reader.json(manifest_path)
                count = len(manifest['planners']) * len(manifest['simulation_seeds'])
            coverage.append({'case_id': 'batch', 'status': state['status'], 'expected_episode_count': count,
                             'raw_episode_count': None, 'included_episode_count': 0,
                             'failed_phase': state.get('failed_phase'), 'error': state.get('error', {})})
    return cases, coverage


def _representatives(rows):
    tie = lambda row: (row['case_id'], int(row['simulation_seed']), row['episode_id'])
    successes = [row for row in rows if row['failure_class'] == 'reached']
    driving = [row for row in rows if row['planning_status'] == 'success' and row['simulation_status'] in {'collision', 'timeout'}]
    planning = [row for row in rows if row['planning_status'] != 'success']
    return (
        ('Success', min(successes, key=lambda row: (-float(row['tracking_rmse_m']), *tie(row))) if successes else None,
         'Highest RMSE among reached episodes; ties: case, seed, episode.'),
        ('Driving failure', min(driving, key=lambda row: (row['simulation_status'] != 'collision', *tie(row))) if driving else None,
         'Collision before timeout; ties: case, seed, episode.'),
        ('Planning failure', min(planning, key=lambda row: (row['planning_status'] != 'planning_error', row['planning_status'], *tie(row))) if planning else None,
         'Planning error first, then status; ties: case, seed, episode.'),
    )


def _render(case, row, output):
    grid, manifest = case['grid'], case['manifest']
    image = Image.new('RGB', (760, 540), '#f7f9fc')
    draw, font = ImageDraw.Draw(image), _font(17)
    title = f'{row["planner"]} | {row["case_id"]} | seed {row["simulation_seed"]} | {row["failure_class"]}'
    draw.text((25, 20), _fit_line(draw, title, font, 710), fill='#14253d', font=font)
    cell = min(700 / grid.width, 380 / grid.height)
    width, height = max(1, int(grid.width * cell) + 1), max(1, int(grid.height * cell) + 1)
    left, top = (760 - width) // 2, 65
    panel = Image.new('RGB', (width, height), 'white')
    paint = ImageDraw.Draw(panel)
    for y, x in zip(*grid.occupied.nonzero()):
        paint.rectangle((x * cell, (grid.height - 1 - y) * cell,
                         (x + 1) * cell, (grid.height - y) * cell), fill='#7a8696')

    def point(x, y):
        return ((float(x) - grid.origin_x) / grid.resolution * cell,
                (grid.height - (float(y) - grid.origin_y) / grid.resolution) * cell)

    samples = case['traces'][row['episode_id']]
    for values, color in ((case['paths'][row['plan_id']], '#9aa8b8'), (samples, '#168777')):
        points = [point(p['x_m'], p['y_m']) for p in values]
        if len(points) > 1:
            paint.line(points, fill=color, width=3)
    for name, color in (('start', '#15803d'), ('goal', '#e11d48')):
        pose = manifest['scenario'][name]
        x, y = point(pose['x'], pose['y'])
        paint.ellipse((x - 5, y - 5, x + 5, y + 5), fill=color)
    terminal = None
    if samples:
        last = samples[-1]
        x, y = point(last['x_m'], last['y_m'])
        paint.line((x - 7, y - 7, x + 7, y + 7), fill='#d97706', width=4)
        paint.line((x - 7, y + 7, x + 7, y - 7), fill='#d97706', width=4)
        terminal = {key: float(last[key]) for key in ('x_m', 'y_m', 'time_s')}
    image.paste(panel, (left, top))
    legend = 'Gray: plan | teal: driven | green: start | pink: goal | orange X: last recorded pose'
    draw.text((25, 465), _fit_line(draw, legend, font, 710), fill='#14253d', font=font)
    note = (f'Last pose: x={terminal["x_m"]:.3f} m, y={terminal["y_m"]:.3f} m, t={terminal["time_s"]:.3f} s'
            if terminal else 'No driving: planning failed; no terminal pose.')
    draw.text((25, 495), _fit_line(draw, note, font, 710), fill='#14253d', font=font)
    with output.open('xb') as stream:
        image.save(stream, format='PNG')
    return terminal


def _h(value):
    return escape(str(value), quote=True)


def _table(headers, rows):
    return '<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{_h(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join(f'<td>{_h(cell)}</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def _median(rows, metric):
    values = [float(row[metric]) for row in rows if row.get(metric, '') != '']
    return f'{float(np.median(values)):.4f} (n={len(values)})' if values else 'n/a (n=0)'


def generate(source, output):
    if output.is_symlink():
        raise ValueError('output directory already exists; choose a new output directory')
    source, output = source.resolve(), output.resolve()
    if output.exists():
        raise ValueError('output directory already exists; choose a new output directory')
    reader = Reader()
    cases, coverage = _load(reader, source)
    groups, pair_groups = defaultdict(list), defaultdict(list)
    for case in cases:
        for row in case['episodes']:
            groups[row['planner']].append(row)
        for row in case['pairs']:
            pair_groups[(row['planner'], row['baseline'])].append(row)
    known = all(row.get('expected_episode_count') is not None for row in coverage)
    expected = sum(row['expected_episode_count'] for row in coverage) if known else None
    included = sum(row['included_episode_count'] for row in coverage)
    missing = expected - included if expected is not None else 'unknown'
    completed = sum(row['status'] == 'complete' for row in coverage)
    parts = [f'<h1>RacePlan results — {_h(source.name)}</h1>',
             f'<p class="coverage">Cases complete: {completed}/{len(coverage)} · Included episodes: {included} · '
             f'Expected episodes: {_h(expected if expected is not None else "unknown")} · Missing episodes: {_h(missing)}</p>',
             '<p>Tables and representatives use completed cases only. Missing cases are not synthesized as episodes.</p>']
    outcomes = []
    for planner, rows in groups.items():
        reached = [row for row in rows if row['failure_class'] == 'reached']
        plan_rows = {f'{row["case_id"]}:{row["plan_id"]}': row for row in rows}.values()
        outcomes.append([planner, f'{len(reached)}/{len(rows)}', sum(r['collision'] == 'True' for r in rows),
                         sum(r['simulation_status'] == 'timeout' for r in rows), sum(r['planning_status'] != 'success' for r in rows),
                         sum(r['planning_status'] == 'planning_error' for r in rows), _median(reached, 'tracking_rmse_m'),
                         _median(reached, 'completion_time_s'), _median(plan_rows, 'runner_planning_time_ms'),
                         _median(plan_rows, 'planning_time_ms')])
    parts += ['<h2>Outcomes first</h2>', _table(['Planner', 'Reached / recorded', 'Collision', 'Timeout', 'Plan failure', 'Incl. error',
              'Reached RMSE median (m)', 'Reached time median (s)', 'Runner wall median (ms, plans)', 'Reported median (ms, plans)'], outcomes)]
    if not outcomes:
        parts.append('<p>No completed-case episodes are available.</p>')
    parts += ['<h2>Case coverage</h2>', _table(['Case', 'Status', 'Expected', 'Raw', 'Included', 'Missing', 'Failure phase', 'Reason'], [
        [row['case_id'], row['status'], row.get('expected_episode_count'), row.get('raw_episode_count'), row['included_episode_count'],
         row['expected_episode_count'] - row['included_episode_count'] if row.get('expected_episode_count') is not None else 'unknown',
         row.get('failed_phase', ''), row.get('error', {}).get('message', '')] for row in coverage])]
    paired = []
    for (planner, baseline), rows in pair_groups.items():
        reached = [row for row in rows if row['both_reached'] == 'True']
        driven = [row for row in rows if row['both_driven'] == 'True']
        paired.append([planner, baseline, len(rows), _median(reached, 'delta_tracking_rmse_m'),
                       _median(reached, 'delta_completion_time_s'), _median(driven, 'delta_driving_min_sampled_clearance_m')])
    parts += ['<h2>Paired differences</h2><p>Planner minus baseline. RMSE/time: both reached. Clearance: both drove, including failures.</p>',
              _table(['Planner', 'Baseline', 'Pairs', 'RMSE delta median (m)', 'Time delta median (s)', 'Clearance delta median (m)'], paired),
              '<h2>Fixed representative selection</h2><p>At most one success, one driving failure, and one planning failure per planner. '
              'Orange X marks the actual last recorded pose; plots show the physical map, without swept-collision guarantees.</p>']
    output.mkdir(parents=True, exist_ok=False)
    (output / 'images').mkdir()
    selected = []
    case_by_id = {case['id']: case for case in cases}
    for planner, rows in groups.items():
        parts.append(f'<h3>{_h(planner)}</h3><div class="cards">')
        for category, row, reason in _representatives(rows):
            parts.append(f'<section><h4>{_h(category)}</h4>')
            if row is None:
                parts.append('<p>No matching recorded episode.</p></section>')
                continue
            asset = f'images/representative_{len(selected):03d}.png'
            terminal = _render(case_by_id[row['case_id']], row, output / asset)
            selected.append({'planner': planner, 'category': category, 'case_id': row['case_id'],
                             'simulation_seed': int(row['simulation_seed']), 'episode_id': row['episode_id'],
                             'outcome': row['failure_class'], 'selection_reason': reason, 'image': asset, 'terminal_pose': terminal})
            parts += [f'<p>Case {_h(row["case_id"])} · seed {_h(row["simulation_seed"])} · {_h(row["failure_class"])}</p>',
                      f'<p>{_h(reason)}</p>', f'<img src="{asset}" alt="{_h(planner)} {_h(category)}">']
            if row['planning_status'] != 'success':
                parts.append('<p>No driving: planning failed; no terminal pose.</p>')
            if row.get('planning_error_message'):
                parts.append(f'<p class="diagnostic">{_h(row.get("planning_error_type", ""))}: {_h(row["planning_error_message"])}</p>')
            parts.append('</section>')
        parts.append('</div>')
    parts += ['<p>Timing values count one plan per case, not seed repeats. Legacy runner timing is n/a. '
              'Historical source hashes need not match the current report generator.</p>', '<p><a href="provenance.json">Provenance and selection records</a></p>']
    css = 'body{font:16px system-ui,sans-serif;margin:28px;color:#14253d;background:#f7f9fc}h1{font-size:28px}.coverage{font-weight:700}table{border-collapse:collapse;background:white;width:100%}th,td{padding:9px;border:1px solid #ccd4df;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere}th{background:#e8edf5}.scroll{overflow-x:auto}.cards{display:flex;gap:16px;flex-wrap:wrap}section{background:white;border:1px solid #ccd4df;padding:14px;flex:1 1 360px;max-width:760px}img{width:100%;height:auto}p{line-height:1.5}.diagnostic{white-space:pre-wrap;overflow-wrap:anywhere}'
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RacePlan results</title><style>' + css + '</style><body>' + ''.join(parts) + '</body></html>'
    (output / 'index.html').write_text(page, encoding='utf-8')
    provenance = {'report_schema_version': 1, 'source': str(source), 'input_sha256': reader.hashes,
                  'generator_source_sha256': {str(path): sha256(path.read_bytes()).hexdigest() for path in sorted(Path(__file__).parent.rglob('*.py'))},
                  'historical_source_sha256': {case['id']: case['manifest'].get('source_sha256', {}) for case in cases},
                  'coverage': {'expected_episodes': expected, 'included_episodes': included, 'missing_episodes': missing},
                  'representatives': selected, 'planning_calls': 0, 'simulation_calls': 0,
                  'output_sha256': {str(path.relative_to(output)): sha256(path.read_bytes()).hexdigest() for path in sorted(output.rglob('*')) if path.is_file()}}
    (output / 'provenance.json').write_text(json.dumps(provenance, indent=2, allow_nan=False), encoding='utf-8')
    return output / 'index.html'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('source', type=Path, help='saved workflow/batch folder or suite folder')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = generate(args.source, args.output_dir)
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        parser.error(str(exc))
    print(f'report={result}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
