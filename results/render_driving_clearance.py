"""Render recorded vehicle clearance, including closest-approach footprints."""
import csv
import json
from pathlib import Path
from statistics import median
from PIL import Image, ImageDraw, ImageFont
from raceplan.common import Pose2D, VehicleGeometry, load_occupancy_map
from raceplan.common.vehicle import footprint_corners

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'results/analysis/driving_clearance_20261013'
PLANNERS = ['dijkstra', 'astar', 'hybrid_astar']
LABELS = ['Dijkstra', 'A*', 'Hybrid A*']
COLORS = ['#2563eb', '#db6b22', '#138f79']
INK, GRAY = '#17283f', '#596b81'
im = Image.new('RGB', (1800, 1550), '#f2f5fa')
d = ImageDraw.Draw(im)
def text(x,y,s,size=24,color=INK,bold=False):
 d.text((x,y),s,fill=color,font=ImageFont.truetype('C:/Windows/Fonts/'+('malgunbd.ttf' if bold else 'malgun.ttf'),size))
def read(path):
 with path.open(newline='',encoding='utf-8-sig') as f: return list(csv.DictReader(f))
def card(box): d.rounded_rectangle(box,radius=18,fill='white')
episodes={s:read(BASE/s/'episodes.csv') for s in ['demo','open']}
samples={s:read(BASE/s/'clearance_samples.csv') for s in ['demo','open']}
text(45,25,'RacePlan | 실제 주행의 장애물 여유 거리',40,bold=True)
text(48,88,'44 tests passed  ·  기존 잡음 파일럿 18 episode 재분석  ·  seed 0 / 1 / 2  ·  충돌 0',25)
text(48,132,'차량 외곽–장애물 거리: 클수록 여유 있음  |  0.05초마다 저장된 실제 위치·방향 사용',23,GRAY)
for n,scenario in enumerate(['demo','open']):
 left=40+n*875
 card((left,195,left+850,670))
 text(left+22,215,'Demo-gap' if scenario=='demo' else 'Open field',30,bold=True)
 text(left+22,263,'색 막대: 주행 최소값의 중앙값 · 점: seed별 최소값',22,GRAY)
 text(left+22,300,'회색 세로선: 계획 최소값  |  서로 다른 위치·표본의 최소값 비교',20,GRAY)
 ox,width=left+195,545
 for tick in [0,10,20,30,40]:
  x=ox+width*tick/40
  d.line((x,350,x,560),fill='#e4eaf2',width=1)
  text(x-10,579,str(tick),20,GRAY)
 for j,planner in enumerate(PLANNERS):
  rows=[r for r in episodes[scenario] if r['planner']==planner]
  values=[float(r['driving_min_sampled_clearance_m'])*100 for r in rows]
  planned=float(rows[0]['min_sampled_footprint_clearance_m'])*100
  y=367+j*71
  text(left+20,y+2,LABELS[j],25,COLORS[j],True)
  end=ox+width*median(values)/40
  d.rectangle((ox,y+9,end,y+37),fill=COLORS[j])
  for value in values:
   x=ox+width*value/40
   d.ellipse((x-4,y+19,x+4,y+27),fill=INK,outline='white',width=1)
  px=ox+width*planned/40
  d.line((px,y,px,y+46),fill='#7b8799',width=3)
  text(max(end,ox+width*max(values)/40)+10,y+3,f'{median(values):.2f}',23,bold=True)
 text(left+22,626,'계획/주행 모두 지도 경계를 포함한 footprint 거리 · 단위 cm',20,GRAY)
text(48,695,'Demo: 가장 가까워진 순간의 차량 footprint',29,bold=True)
text(48,740,'각 planner의 3개 seed 중 최솟값을 선택 · 같은 좌표 범위로 확대 · 색 실선은 해당 seed의 실제 주행',21,GRAY)
grid=load_occupancy_map(ROOT/'maps/demo.yaml').grid
manifest=json.loads((ROOT/'results/raw/pilot_20261012/demo_noise_manifest.json').read_text())
vehicle=VehicleGeometry(**manifest['vehicle'])
for j,planner in enumerate(PLANNERS):
 left=40+j*580
 card((left,792,left+560,1272))
 row=min((r for r in samples['demo'] if r['episode_id'].startswith(planner+':')),key=lambda r:float(r['footprint_clearance_m']))
 text(left+20,807,f'{LABELS[j]}  |  {float(row["footprint_clearance_m"])*100:.2f} cm',27,COLORS[j],True)
 text(left+20,850,f'seed {row["episode_id"].split(":")[1]} · t = {float(row["time_s"]):.2f} s',22,GRAY)
 # Pixel clipping keeps the same zoom viewport across planner panels.
 tile=Image.new('RGB',(490,336),'#f8fafc'); td=ImageDraw.Draw(tile)
 scale=140
 def point(x,y): return ((x-4)*scale,(5.1-y)*scale)
 for r in range(grid.height):
  for c in range(grid.width):
   a=point(c,r+1); b=point(c+1,r)
   td.rectangle((*a,*b),fill='#cdd6e2' if grid.occupied[r,c] else '#f8fafc',outline='#e0e6ee')
 track=[point(float(r['x_m']),float(r['y_m'])) for r in samples['demo'] if r['episode_id']==row['episode_id']]
 td.line(track,fill=COLORS[j],width=4)
 pose=Pose2D(float(row['x_m']),float(row['y_m']),float(row['yaw_rad']))
 corners=[point(x,y) for x,y in footprint_corners(pose,vehicle)]
 td.polygon(corners,fill='#ffe6a7',outline=INK,width=3)
 center=point(pose.x,pose.y)
 td.ellipse((center[0]-3,center[1]-3,center[0]+3,center[1]+3),fill=INK)
 im.paste(tile,(left+35,905))
text(48,1300,'결과가 의미하는 것',27,bold=True)
text(48,1345,'• Demo Hybrid A*: 계획 최소 5.30 cm → 주행 최저 1.42 cm. 낮은 RMSE와 큰 안전 여유는 별개입니다.',23)
text(48,1385,'• Open: 세 planner의 최소값은 모두 공통 초기 상태(t=0)에서 발생해 경로 차이를 구별하지 못했습니다.',23)
text(48,1425,'• 표본 사이 충돌을 보장하는 지표는 아닙니다. 종료 위치·자세가 달라 계획–주행 차이를 손실로 단정할 수 없습니다.',21,GRAY)
text(48,1485,'2026-10-13  |  소형 지도 2개 · query 각 1개 · 일반적인 planner 우열 및 충돌 확률을 의미하지 않음',20,GRAY)
out=ROOT/'results/figures/driving_clearance_report.png'; out.parent.mkdir(parents=True, exist_ok=True); im.save(out); print(out)
