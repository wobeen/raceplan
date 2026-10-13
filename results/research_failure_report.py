"""Representative held-out failure views, using saved true trajectories and geometry."""
import argparse
import csv
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from math import cos,sin
from raceplan.common import Pose2D,VehicleGeometry,load_occupancy_map
from raceplan.common.vehicle import footprint_corners
from raceplan.common.planning_space import circle_planning_grid
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--name',default='research_20261013');a=p.parse_args()
if Path(a.name).name!=a.name or a.name in {'.','..'}:p.error('invalid run name')
def read(path):
 if not path.exists():return []
 with path.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
raw=ROOT/'results/raw'/a.name/'evaluation'
im=Image.new('RGB',(1800,1580),'#f2f5fa');d=ImageDraw.Draw(im)
def t(x,y,s,size=24,color='#17283f',bold=False):
 d.text((x,y),s,fill=color,font=ImageFont.truetype('C:/Windows/Fonts/'+('malgunbd.ttf' if bold else 'malgun.ttf'),size))
t(45,25,'대표 실패 | 계획 실패 · 주행 충돌 · 방향 미달을 분리',37,bold=True)
t(48,85,'회색: 물리 장애물 · 옅은 파랑: grid planner의 추가 여유 · 색: 계획 · 검정: 주행 · 노랑: 종료 차량',22)
choices=[('gate','astar','보수적인 원형 여유로 계획 경로 없음'),('slalom','hybrid_astar','계획은 성공했지만 실제 주행 충돌'),
         ('turn','astar','위치는 도달했지만 최종 방향 미달'),('heading','hybrid_astar','계획과 추종의 차이가 장애물 접촉으로 연결')]
for j,(family,planner,caption) in enumerate(choices):
 folder=raw/f'evaluation_{family}_1_q0';config=json.loads((folder/'configuration.json').read_text())
 vehicle=VehicleGeometry(**config['vehicle']);grid=load_occupancy_map(folder/'map.yaml').grid
 design=json.loads((folder/'design.json').read_text());start=Pose2D(**design['start']);goal=Pose2D(**design['goal'])
 left=40+(j%2)*880;top=145+(j//2)*670
 d.rounded_rectangle((left,top,left+850,top+645),radius=16,fill='white')
 t(left+20,top+16,f'{family} / {planner} / seed 3',27,bold=True)
 t(left+20,top+57,caption,23)
 ox,oy,scale=left+78,top+105,80
 planning=circle_planning_grid(grid,vehicle) if planner=='astar' else grid
 for r in range(grid.height):
  for c in range(grid.width):
   x,y=ox+c*grid.resolution*scale,oy+(grid.height-r-1)*grid.resolution*scale
   if planning.occupied[r,c]:
    d.rectangle((x,y,x+grid.resolution*scale+.5,y+grid.resolution*scale+.5),fill='#cbd3df' if grid.occupied[r,c] else '#dceafa')
 def xy(x,y):return ox+x*scale,oy+(6-y)*scale
 path=[r for r in read(folder/'paths.csv') if r['planner']==planner]
 track=[r for r in read(folder/'trajectory.csv') if r['planner']==planner and r['seed']=='3']
 color='#138e77' if planner=='hybrid_astar' else '#d87124'
 if path:d.line([xy(float(r['x']),float(r['y'])) for r in path],fill=color,width=5)
 if track:
  d.line([xy(float(r['x']),float(r['y'])) for r in track],fill='#17283f',width=2)
  end=track[-1];pose=Pose2D(float(end['x']),float(end['y']),float(end['yaw']))
  d.polygon([xy(x,y) for x,y in footprint_corners(pose,vehicle)],fill='#ffe4a0',outline='#17283f',width=2)
 for pose,label in [(start,'S'),(goal,'G')]:
  x,y=xy(pose.x,pose.y);t(x-8,y-31,label,20,bold=True)
  d.line((x,y,x+30*cos(pose.yaw),y-30*sin(pose.yaw)),fill='#9b3884',width=3)
 outcome=next(r for r in read(folder/'episodes.csv') if r['planner']==planner and r['seed']=='3')
 yaw=outcome['goal_yaw_error_rad']
 t(left+20,top+596,f"{outcome['planning_status']} / {outcome['driving_status']} · 방향 오차: "+(f'{float(yaw):.2f} rad' if yaw else '주행 없음'),22)
t(50,1510,'2026-10-13 · 미사용 지도 결과를 본 뒤 설정을 수정하지 않음 · snapshot은 전체 궤적 중 대표 episode',22)
out=ROOT/'results/figures'/a.name/'failures.png';out.parent.mkdir(parents=True,exist_ok=True);im.save(out);print(out)
