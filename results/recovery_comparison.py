"""Paired baseline/guard/recovery diagnostic from frozen validation paths.

No tuning or new held-out claim. All outputs go into a new directory. Planner
wall time is reported separately from fixed-step simulated driving/stopping time.
"""
import argparse
import hashlib
import json
import platform
from dataclasses import asdict, replace
from pathlib import Path as FilePath
from statistics import mean

from PIL import Image, ImageDraw, ImageFont

from raceplan.common import Path, Pose2D, VehicleGeometry
from raceplan.controllers import PIDConfig, PurePursuitConfig
from raceplan.research_design import Case, build
from raceplan.research_engine import BASELINES, planner
from raceplan.common.planning_space import circle_planning_grid
from raceplan.simulator import NoiseConfig, RecoveryConfig, SimulationConfig, run_episode
from raceplan.simulator.obstacle_guard import ObstacleGuardConfig

ROOT = FilePath(__file__).resolve().parents[1]
MODES = ('baseline', 'guard', 'recovery')
STATUSES = ('reached', 'collision', 'timeout', 'planning_failed', 'recovery_failed')


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(out, summary, traces, designs, paths):
    font_path = 'C:/Windows/Fonts/malgun.ttf'
    font = lambda size: ImageFont.truetype(font_path, size)
    image = Image.new('RGB', (1840, 970), '#f3f6fa')
    draw = ImageDraw.Draw(image)
    def text(x, y, value, size=23):
        draw.text((x, y), value, fill='#17283f', font=font(size))
    text(30, 20, '동일 저장 경로·seed 비교 | ' + ' / '.join(dict.fromkeys(r['mode'] for r in summary)), 34)
    text(30, 76, '성공 = 충돌 없이 목표 위치 0.5m 이내. yaw 제외. validation 재사용 진단이며 새 held-out 검증 아님.', 22)
    columns = [30, 350, 445, 570, 680, 800, 950, 1110, 1280, 1460, 1630]
    headers = ['플래너 / 조건', '건수', '성공', '충돌', 'timeout', '계획실패', '회복실패', '주행 평균s', '정지 평균s', '재계획 합', '재출발 합']
    for x, label in zip(columns, headers):
        text(x, 130, label, 20)
    labels = dict(baseline='기존', guard='guard', recovery='회복 v1',
                  recovery_v1='회복 v1', recovery_v2='회복 v2')
    for i, row in enumerate(summary):
        y = 185 + i * 70
        values = [row['planner'] + ' / ' + labels[row['mode']], row['n'],
                  row['reached'], row['collision'], row['timeout'], row['planning_failed'],
                  row['recovery_failed'], f"{row['mean_driving_time_s']:.2f}",
                  f"{row['mean_stopped_time_s']:.2f}", row['replan_count'], row['restart_count']]
        for x, value in zip(columns, values):
            text(x, y, str(value))
    text(30, 845, '주행/정지 시간은 시뮬레이션 시간: 각 step 시작 속도 ≤ 0.03m/s이면 정지로 집계. planning wall time은 별도 JSON.', 20)
    text(30, 895, '샘플 충돌 검사·완전한 정적 지도·true pose 기반. swept collision, 동적 장애물, 센서 오차/제동 지연 보장 없음.', 20)
    image.save(out / 'comparison.png')

    # Each planner receives all cases and seeds, so a representative seed cannot hide failures.
    colors = dict(baseline='#c44f52', guard='#326ec1', recovery='#158979',
                  recovery_v1='#326ec1', recovery_v2='#158979')
    for name in BASELINES:
        case_names = list(designs)
        seed_count = len({t['seed'] for t in traces})
        canvas = Image.new('RGB', (max(1740, seed_count * 575 + 25), 130 + len(case_names) * 365), 'white')
        d = ImageDraw.Draw(canvas)
        legend = ' / '.join(f"{labels[mode]} ({colors[mode]})" for mode in dict.fromkeys(t['mode'] for t in traces))
        d.text((25, 15), f'{name} | {legend} | × 회복 이벤트 위치',
               font=font(25), fill='#17283f')
        for row, case_name in enumerate(case_names):
            grid, start, goal, rectangles = build(designs[case_name])
            seeds = sorted({t['seed'] for t in traces if t['case'] == case_name})
            for col, seed in enumerate(seeds):
                ox, oy, scale = 25 + col * 575, 125 + row * 365, 56
                xy = lambda p: (ox + p.x * scale, oy + (6 - p.y) * scale)
                d.text((ox, oy - 35), f'{case_name} / seed {seed}', font=font(17), fill='#17283f')
                for x0, y0, x1, y1 in rectangles:
                    d.rectangle((ox + x0*scale, oy + (6-y1)*scale,
                                 ox + x1*scale, oy + (6-y0)*scale), fill='#c9cdd3')
                original = paths[(case_name, name)]
                if original and len(original.poses) > 1:
                    d.line([xy(p) for p in original.poses], fill='#a8adb7', width=1)
                gx, gy = xy(goal)
                d.ellipse((gx-5, gy-5, gx+5, gy+5), outline='#17283f', width=2)
                for trace in traces:
                    if (trace['case'], trace['planner'], trace['seed']) != (case_name, name, seed):
                        continue
                    points = [xy(Pose2D(**s['state']['pose'])) for s in trace['samples']]
                    if len(points) > 1:
                        d.line(points, fill=colors[trace['mode']], width=2)
                    x, y = points[-1]
                    d.ellipse((x-3, y-3, x+3, y+3), fill=colors[trace['mode']])
                    for event in trace['recovery_events']:
                        x, y = xy(Pose2D(**event['pose']))
                        d.line((x-4, y-4, x+4, y+4), fill='#17283f', width=2)
                        d.line((x-4, y+4, x+4, y-4), fill='#17283f', width=2)
        canvas.save(out / f'trajectories_{name}.png')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=FilePath, default=ROOT/'results/analysis/obstacle_guard_20261013')
    parser.add_argument('--output', type=FilePath, default=None)
    parser.add_argument('--compare-v2', action='store_true', help='paired recovery v1 versus v2; no retuning')
    parser.add_argument('--seeds', type=int, nargs='+', default=None)
    parser.add_argument('--planning-timeout', type=float, default=3.0)
    args = parser.parse_args(argv)
    if args.planning_timeout <= 0:
        parser.error('--planning-timeout must be positive')
    source = args.source.resolve()
    manifest_file, paths_file = source/'manifest.json', source/'paths.json'
    old = json.loads(manifest_file.read_text(encoding='utf-8'))
    saved = json.loads(paths_file.read_text(encoding='utf-8'))
    designs = {c['name']: Case(**c) for c in old['cases']}
    seeds = args.seeds if args.seeds is not None else old['seeds']
    if len(seeds) != len(set(seeds)) or not seeds:
        parser.error('seeds must be nonempty and unique')
    vehicle = VehicleGeometry(**old['vehicle'])
    tracker_data = dict(old['tracker'])
    tracker_data['speed_pid'] = PIDConfig(**tracker_data['speed_pid'])
    tracker = PurePursuitConfig(**tracker_data)
    simulation = SimulationConfig(**{**old['simulation'], 'goal_tolerance': .5, 'goal_yaw_tolerance': None})
    noise = NoiseConfig(**old['noise'])
    guard = ObstacleGuardConfig(**old['obstacle_guard'])
    recovery = RecoveryConfig(policy_version=1)
    modes = ('recovery_v1', 'recovery_v2') if args.compare_v2 else MODES
    recovery_configs = {mode: replace(recovery, policy_version=2 if mode == 'recovery_v2' else 1)
                        for mode in modes if mode.startswith('recovery')}
    paths = {}
    for item in saved:
        key = (item['case'], item['planner'])
        if key in paths:
            raise ValueError(f'duplicate saved path: {key}')
        data = item['path']
        paths[key] = Path(tuple(Pose2D(**p) for p in data['poses']), data['cost']) if data else None
    expected = {(c, p) for c in designs for p in BASELINES}
    if set(paths) != expected:
        raise ValueError('saved paths must contain exactly every case/planner pair')
    default_output = ROOT/'results/analysis'/('recovery_v2_20261013' if args.compare_v2 else 'recovery_20261013')
    out = (args.output or default_output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    sources = sorted((ROOT/'src/raceplan').rglob('*.py')) + [FilePath(__file__)]
    dump(out/'manifest.json', dict(
        purpose='paired validation diagnostic, not new held-out evaluation',
        inputs={str(p): sha(p) for p in (manifest_file, paths_file)},
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
        python=platform.python_version(), cases=old['cases'], seeds=seeds,
        vehicle=asdict(vehicle), tracker=asdict(tracker), simulation=asdict(simulation),
        noise=asdict(noise), obstacle_guard=asdict(guard), recovery=asdict(recovery),
        modes=modes, recovery_configs={mode: asdict(config) for mode, config in recovery_configs.items()},
        success_criterion='collision-free position within 0.5m, yaw excluded',
        replan_policy='same planner and planning grid, fully stopped current true pose; no teleport; controller reset',
        planning_timeout_s=args.planning_timeout,
        timing='fixed simulation clock; planning wall time excluded and recorded separately',
        stop_threshold_mps=recovery.stop_speed_mps))
    dump(out/'paths.json', saved)
    rows, traces = [], []
    for case_name, case in designs.items():
        grid, start, goal, _ = build(case)
        planning_grid = circle_planning_grid(grid, vehicle)
        for name in BASELINES:
            algorithm = planner(name)
            target_grid = grid if name == 'hybrid_astar' else planning_grid
            def replan(pose, destination):
                return algorithm.plan(target_grid, pose, destination, timeout_s=args.planning_timeout)
            for seed in seeds:
                for mode in modes:
                    row = dict(case=case_name, planner=name, seed=seed, mode=mode,
                               status='planning_failed', position_success=False,
                               collision=False, goal_distance_m=None, time_s=0.0,
                               driving_time_s=0.0, stopped_time_s=0.0, restart_count=0,
                               replan_count=0, replanning_time_s=0.0,
                               replan_validation_time_s=0.0,
                               planning_failure_stage='initial', recovery_reason=None)
                    path = paths[(case_name, name)]
                    if path is not None:
                        result = run_episode(grid, path, goal, vehicle, tracker, simulation,
                            initial_pose=start, simulation_seed=seed, noise=noise,
                            obstacle_guard=None if mode == 'baseline' else guard,
                            recovery=recovery_configs.get(mode),
                            replanner=replan if mode in recovery_configs else None)
                        row.update(status=result.status.value, position_success=result.reached,
                                   collision=result.collided, goal_distance_m=result.goal_distance,
                                   time_s=result.completion_time_s, driving_time_s=result.driving_time_s,
                                   stopped_time_s=result.stopped_time_s, restart_count=result.restart_count,
                                   replan_count=result.replan_count, replanning_time_s=result.replanning_time_s,
                                   replan_validation_time_s=result.replan_validation_time_s,
                                   planning_failure_stage='recovery' if result.status.value == 'planning_failed' else None,
                                   recovery_reason=result.recovery_reason)
                        traces.append(dict(case=case_name, planner=name, seed=seed, mode=mode,
                                           status=result.status.value,
                                           samples=[asdict(s) for s in result.samples],
                                           recovery_events=[asdict(e) for e in result.recovery_events]))
                    rows.append(row)
        # Persist completed cases if a later run or render fails; never overwrite old run directories.
        dump(out/'episodes.json', rows)
        dump(out/'trajectories.json', traces)
        print(case_name, flush=True)
    summary = []
    for name in BASELINES:
        for mode in modes:
            subset = [r for r in rows if r['planner'] == name and r['mode'] == mode]
            summary.append(dict(planner=name, mode=mode, n=len(subset),
                **{s: sum(r['status'] == s for r in subset) for s in STATUSES},
                mean_driving_time_s=mean(r['driving_time_s'] for r in subset),
                mean_stopped_time_s=mean(r['stopped_time_s'] for r in subset),
                restart_count=sum(r['restart_count'] for r in subset),
                replan_count=sum(r['replan_count'] for r in subset),
                replanning_time_s=sum(r['replanning_time_s'] for r in subset),
                replan_validation_time_s=sum(r['replan_validation_time_s'] for r in subset)))
    dump(out/'summary.json', summary)
    render(out, summary, traces, designs, paths)
    dump(out/'complete.json', dict(artifacts={p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == '__main__':
    main()
