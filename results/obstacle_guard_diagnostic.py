"""Position-only obstacle-guard diagnostic on validation maps; not held-out evaluation."""
from dataclasses import asdict, replace
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont
from raceplan.common.planning_space import circle_planning_grid
from raceplan.defaults import baseline_vehicle, baseline_tracker_config, baseline_simulation_config
from raceplan.research_design import cases, build
from raceplan.research_engine import BASELINES, NOISE, planner
from raceplan.simulator import run_episode
from raceplan.simulator.obstacle_guard import ObstacleGuardConfig

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/analysis/obstacle_guard_20261013'
FIG = ROOT / 'results/figures/obstacle_guard_20261013.png'


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    vehicle = baseline_vehicle()
    tracker = baseline_tracker_config()
    config = replace(baseline_simulation_config(), goal_yaw_tolerance=None)
    guard = ObstacleGuardConfig()
    manifest = dict(purpose='validation diagnostic; no new held-out claim',
                    seeds=[0, 1, 2], vehicle=asdict(vehicle), tracker=asdict(tracker),
                    obstacle_guard=asdict(guard), simulation=asdict(config), noise=asdict(NOISE), success_criterion='position only, collision checked first',
                    cases=[asdict(c) for c in cases('validation')],
                    source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sorted((ROOT/'src/raceplan').rglob('*.py'))})
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    saved_paths = []
    rows = []
    traces = []
    for case in cases('validation'):
        grid, start, goal, _ = build(case)
        planning_grid = circle_planning_grid(grid, vehicle)
        for name in BASELINES:
            plan = planner(name).plan(grid if name == 'hybrid_astar' else planning_grid,
                                      start, goal, timeout_s=3)
            saved_paths.append(dict(case=case.name, planner=name, path=asdict(plan.path) if plan.path else None))
            for seed in [0, 1, 2]:
                paired = []
                for mode, active_guard in [('constant', None), ('guard', guard)]:
                    row = dict(case=case.name, planner=name, seed=seed, mode=mode,
                               planning_status=plan.status.value, status='no_path', position_success=False)
                    if plan.path is not None:
                        result = run_episode(grid, plan.path, goal, vehicle, tracker,
                            config,
                            initial_pose=start, simulation_seed=seed, noise=NOISE, obstacle_guard=active_guard)
                        paired.append(result)
                        row.update(status=result.status.value, position_success=result.reached,
                                   final_distance=result.goal_distance, final_yaw_error=result.goal_yaw_error,
                                   time_s=result.completion_time_s, final_speed=result.samples[-1].state.speed)
                        traces.append(dict(case=case.name, planner=name, seed=seed, mode=mode,
                                           samples=[asdict(s) for s in result.samples]))
                    rows.append(row)
        print(case.name, flush=True)
    (OUT/'paths.json').write_text(json.dumps(saved_paths), encoding='utf-8')
    (OUT/'episodes.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')
    (OUT/'trajectories.json').write_text(json.dumps(traces), encoding='utf-8')
    summary = []
    for name in BASELINES:
        for mode in ['constant', 'guard']:
            subset = [r for r in rows if r['planner'] == name and r['mode'] == mode]
            summary.append(dict(planner=name, mode=mode, n=len(subset),
                                position_success=sum(r['position_success'] for r in subset),
                                **{s: sum(r['status'] == s for r in subset)
                                   for s in ['reached', 'collision', 'timeout', 'no_path']}))
    (OUT/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    im = Image.new('RGB', (1500, 780), '#f3f6fa'); draw = ImageDraw.Draw(im)
    def text(x, y, value, size=25, color='#17283f'):
        draw.text((x, y), value, fill=color, font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', size))
    text(40, 25, '위치 도달 기준 | 기존 제어 vs 장애물 감속·정지', 38)
    text(40, 85, '동일 경로·조향 제어·노이즈 seed | validation 8개 질의 × 3 seeds × 3 planners × 2조건 = 144건')
    text(40, 145, '플래너 / 속도 정책                 위치 성공 (24건 기준)                   충돌       시간초과       계획실패')
    for i, r in enumerate(summary):
        y = 205 + i * 75
        text(40, y, r['planner'] + (' / 일정속도' if r['mode']=='constant' else ' / 장애물제어'))
        draw.rectangle((490, y+5, 850, y+35), fill='#dfe6ef')
        if r['position_success']:
            draw.rectangle((490, y+5, 490+360*r['position_success']/24, y+35), fill='#208e80')
        text(870, y, str(r['position_success']))
        text(1010, y, str(r['collision'])); text(1160, y, str(r['timeout'])); text(1340, y, str(r['no_path']))
    text(40, 685, '성공: 충돌 없이 목표 위치 0.5 m 이내 진입. 방향 제외. 정지 후 미도달은 시간초과로 집계.', 23)
    text(40, 727, '기존 validation 재사용 진단이며 새 held-out 검증이 아닙니다. 이전 평가 원본은 보존됩니다.', 23)
    FIG.parent.mkdir(parents=True, exist_ok=True); im.save(FIG)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
