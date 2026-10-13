"""Render controlled gate-width validation pilot from measured artifacts."""
import csv
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from raceplan.common import load_occupancy_map, Pose2D, VehicleGeometry
from raceplan.common.vehicle import footprint_corners
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'results/analysis/corridor_width_20261013'
RAW=ROOT/'results/raw/corridor_width_20261013'
P=['dijkstra','astar','hybrid_astar']; L=['Dijkstra','A*','Hybrid A*']; C=['#2563eb','#dc7027','#108f78']
def read(path):
 with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
rows=read(BASE/'width_comparison.csv')
im=Image.new('RGB',(1800,1660),'#f2f5fa');d=ImageDraw.Draw(im)
def t(x,y,s,size=24,color='#17283f',bold=False):
 d.text((x,y),s,fill=color,font=ImageFont.truetype('C:/Windows/Fonts/'+('malgunbd.ttf' if bold else 'malgun.ttf'),size))
def card(box):d.rounded_rectangle(box,radius=18,fill='white')
t(45,25,'RacePlan | 통로 폭만 줄이면 무엇이 달라질까?',39,bold=True)
t(48,87,'46 tests passed · 5개 폭 × 3 planner × 3 seed × 무잡음/잡음 = 90 episode 항목',25)
t(48,131,'격자 0.1 m · 차량 폭 0.31 m · 동일 시작/목표·controller · inflation 0 m · validation 파일럿',23,'#56677e')
card((40,190,1760,575))
t(63,207,'결과 분류: 각 칸은 seed 3개의 결과 (무잡음과 잡음 조건 동일)',27,bold=True)
xs=[390,655,920,1185,1450]
for x,w in zip(xs,['1.3 m','0.9 m','0.7 m','0.5 m','0.3 m']):t(x+30,257,w,27,bold=True)
labels={'reached':('도달 3/3','#daf1e8','#146348'),'driving_collision':('충돌 3/3','#ffe0d8','#aa3927'),'planning_no_path':('계획 실패 3/3','#e4e8f0','#53617a')}
for j,p in enumerate(P):
 y=312+j*78;t(70,y+15,L[j],28,C[j],True)
 for x,w in zip(xs,['1.3','0.9','0.7','0.5','0.3']):
  rs=[r for r in rows if r['width_m']==w and r['condition']=='noise' and r['planner']==p]
  assert len(rs)==3 and len({r['failure_class'] for r in rs})==1
  label,bg,fg=labels[rs[0]['failure_class']]
  d.rounded_rectangle((x,y,x+235,y+61),radius=10,fill=bg);t(x+20,y+14,label,25,fg,True)
t(55,597,'폭 0.7 m 사례 | 계획은 했지만 주행이 가능한가?',30,bold=True)
t(55,641,'seed 0 · 색 실선: 계획 · 검정 선: 실제 주행 · 노란 사각형: 종료 시 차량',23,'#56677e')
grid=load_occupancy_map(ROOT/'scenarios/corridor_width/gate_07_map.yaml').grid
paths=read(RAW/'gate_07_noise_paths.csv');trajectories=read(RAW/'gate_07_noise_trajectory.csv')
vehicle=VehicleGeometry(**json.loads((RAW/'gate_07_noise_manifest.json').read_text())['vehicle'])
for j,p in enumerate(P):
 left=40+j*580;card((left,690,left+560,1090));t(left+20,705,L[j],28,C[j],True)
 ox,oy,scale=left+32,755,62
 for r in range(grid.height):
  for c in range(grid.width):
   x,y=ox+c*.1*scale,oy+(grid.height-r-1)*.1*scale
   if grid.occupied[r,c]:d.rectangle((x,y,x+.1*scale+1,y+.1*scale+1),fill='#c9d3e0')
 def xy(r):return ox+float(r['x_m'])*scale,oy+(4.1-float(r['y_m']))*scale
 route=[xy(r) for r in paths if r['plan_id']==p]
 track=[r for r in trajectories if r['episode_id']==p+':0']
 d.line(route,fill=C[j],width=5);d.line([xy(r) for r in track],fill='#28344b',width=2)
 end=track[-1];pose=Pose2D(float(end['x_m']),float(end['y_m']),float(end['yaw_rad']))
 corners=[(ox+x*scale,oy+(4.1-y)*scale) for x,y in footprint_corners(pose,vehicle)]
 d.polygon(corners,fill='#ffe2a0',outline='#17283f',width=2)
 for x,y,tag in [(1.05,1.55,'S'),(6.95,2.55,'G')]:t(ox+x*scale-8,oy+(4.1-y)*scale-32,tag,20,bold=True)
 status='충돌' if j<2 else '도달'
 t(left+20,1033,f'{status} · t = {float(end["time_s"]):.2f} s',24,bold=True)
card((40,1115,1760,1420))
t(62,1130,'실제 주행 최소 clearance | 잡음 seed 3개 중 최솟값 (cm)',27,bold=True)
for x,w in zip(xs,['1.3 m','0.9 m','0.7 m','0.5 m','0.3 m']):t(x+35,1179,w,23,bold=True)
for j,p in enumerate(P):
 y=1228+j*53;t(65,y,L[j],25,C[j],True)
 for x,w in zip(xs,['1.3','0.9','0.7','0.5','0.3']):
  vals=[float(r['driving_min_sampled_clearance_m'])*100 for r in rows if r['width_m']==w and r['condition']=='noise' and r['planner']==p and r['driving_min_sampled_clearance_m']]
  t(x+35,y,f'{min(vals):.2f}' if vals else '주행 없음',24)
t(50,1440,'해석: 이 query에서는 통로 폭 감소가 계획–주행 실패 차이를 드러냈습니다.',25,bold=True)
t(50,1485,'• Grid planner는 점 기준, Hybrid A*는 차량 footprint 기준입니다. 차량 표현 차이가 결과에 포함됩니다.',22,'#56677e')
t(50,1524,'• 0.5 m의 no_path는 현재 탐색 이산화의 한계일 수 있습니다. 0.3 m는 차량 폭보다 좁은 음성 대조입니다.',22,'#56677e')
t(50,1563,'• 무잡음 seed 반복은 독립 표본이 아닙니다. query 1개의 파일럿으로 일반적 우열·성공 확률을 확정하지 않습니다.',21,'#56677e')
t(50,1610,'2026-10-13 · results/analysis/corridor_width_20261013/width_comparison.csv',20,'#56677e')
out=ROOT/'results/figures/corridor_width_report.png';im.save(out);print(out)
