"""Explain saved guard timeouts without rerunning or altering frozen episodes."""
import hashlib
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from raceplan.common import Pose2D, VehicleGeometry
from raceplan.common.vehicle import footprint_corners
from raceplan.metrics import Clearance
from raceplan.research_design import Case, build
from raceplan.simulator.kinematic import SimulationConfig
from raceplan.simulator.obstacle_guard import ObstacleGuardConfig, guard_diagnostics
from raceplan.planners.hybrid_primitives import rollout_bicycle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'results/analysis/obstacle_guard_20261013'
OUT = ROOT/'results/analysis/guard_stop_20261013'
FIG = ROOT/'results/figures/guard_stop_20261013.png'


def main():
    manifest = json.loads((SOURCE/'manifest.json').read_text())
    episodes = json.loads((SOURCE/'episodes.json').read_text())
    traces = json.loads((SOURCE/'trajectories.json').read_text())
    paths = json.loads((SOURCE/'paths.json').read_text())
    vehicle = VehicleGeometry(**manifest['vehicle'])
    sim = SimulationConfig(**manifest['simulation'])
    config = ObstacleGuardConfig(**manifest['obstacle_guard'])
    cases = {c['name']: Case(**c) for c in manifest['cases']}
    keys = {(r['case'], r['planner'], r['seed']) for r in episodes
            if r['mode'] == 'guard' and r['status'] == 'timeout'}
    rows, representatives = [], {}
    for trace in traces:
        key = trace['case'], trace['planner'], trace['seed']
        if trace['mode'] != 'guard' or key not in keys:
            continue
        grid, _, goal, rectangles = build(cases[trace['case']])
        last = trace['samples'][-1]
        pose = Pose2D(**last['state']['pose'])
        diagnostic = guard_diagnostics(grid, Clearance(grid), pose, last['state']['speed'],
                                       last['steering_angle'], vehicle, sim, config)
        lateral = diagnostic['lateral_cap_mps'] <= 1e-9
        forward = diagnostic['braking_cap_mps'] <= 1e-9
        reason = 'both' if lateral and forward else 'lateral_only' if lateral else 'forward_only' if forward else 'other'
        row = dict(case=key[0], planner=key[1], seed=key[2], reason=reason,
                   final_pose=asdict(pose), final_speed=last['state']['speed'],
                   steering_rad=last['steering_angle'], goal_distance_m=((goal.x-pose.x)**2+(goal.y-pose.y)**2)**.5,
                   **diagnostic)
        rows.append(row)
        representatives.setdefault('전방 충돌 예측 있음' if diagnostic['preview_collision'] else '전방 충돌 예측 없음', (trace, row, rectangles, goal))
    counts = dict(Counter(r['reason'] for r in rows))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'stops.json').write_text(json.dumps(rows, indent=2))
    (OUT/'summary.json').write_text(json.dumps(dict(n=len(rows), counts=counts), indent=2))
    (OUT/'manifest.json').write_text(json.dumps(dict(
        purpose='Saved validation final-state diagnosis; not a new safety evaluation',
        classification='zero speed caps at final pose and last applied steering; future collision is a separate field',
        inputs={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE.glob('*.json')},
        source_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in [Path(__file__), ROOT/'src/raceplan/simulator/obstacle_guard.py']}), indent=2))
    im = Image.new('RGB', (1500, 900), '#f3f6fa')
    d = ImageDraw.Draw(im)
    def text(x, y, message, size=24):
        d.text((x,y), message, font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf', size), fill='#17283f')
    text(35, 20, 'Hybrid A* 정지 원인 | 저장된 18개 timeout의 최종 상태', 34)
    text(35, 75, '측면 제한만 0: %d / 전방 제한만 0: %d / 둘 다 0: %d / 기타: %d' % tuple(counts.get(k,0) for k in ['lateral_only','forward_only','both','other']))
    text(35, 115, '측면 제한만 0이어도 전방 예측 충돌이 있을 수 있습니다. 제한 해제의 안전성을 뜻하지 않습니다.', 22)
    for index, (reason, (trace, row, rectangles, goal)) in enumerate(list(representatives.items())[:2]):
        ox, oy, scale = 40 + index*740, 225, 85
        def xy(x,y): return ox+x*scale, oy+(6-y)*scale
        text(ox, 170, f'{reason} | {row["case"]} / seed {row["seed"]}', 20)
        for x0,y0,x1,y1 in rectangles:
            d.rectangle((*xy(x0,y1), *xy(x1,y0)), fill='#8994a3')
        path = next(p['path'] for p in paths if p['case']==row['case'] and p['planner']==row['planner'])
        d.line([xy(p['x'],p['y']) for p in path['poses']], fill='#a9b5c5', width=3)
        d.line([xy(s['state']['pose']['x'],s['state']['pose']['y']) for s in trace['samples']], fill='#168b80', width=4)
        pose = Pose2D(**row['final_pose'])
        preview = rollout_bicycle(pose, steering_angle=row['steering_rad'], signed_distance=config.horizon_m,
                                  wheelbase=vehicle.wheelbase, sample_distance=config.sample_distance_m)
        d.line([xy(p.x,p.y) for p in preview], fill='#e69a24', width=4)
        d.polygon([xy(x,y) for x,y in footprint_corners(pose,vehicle)], outline='#d84343', width=3)
        gx,gy=xy(goal.x,goal.y); d.ellipse((gx-7,gy-7,gx+7,gy+7),fill='#334ed0')
        text(ox, 750, f'여유 {row["clearance_m"]:.3f} m | 목표 거리 {row["goal_distance_m"]:.2f} m', 22)
        text(ox, 788, f'전방 예측 충돌: {row["preview_collision"]} | 제동 속도 상한 {row["braking_cap_mps"]:.2f} m/s', 21)
    text(35, 850, '회색: 계획 경로 / 초록: 실제 궤적 / 주황: 고정 조향 1m 예측 / 빨강: 정지 차체 / 파랑: 목표', 23)
    im.save(FIG)
    print(json.dumps(dict(n=len(rows), counts=counts, preview_collision=sum(r['preview_collision'] for r in rows)), indent=2))


if __name__ == '__main__':
    main()
