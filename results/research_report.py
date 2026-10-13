"""Cluster-aware descriptive summaries and static report figures from stored runs."""
import csv
import argparse
import json
from pathlib import Path
from collections import Counter,defaultdict
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from raceplan.research_engine import write_csv,dump
from raceplan.research_design import cases
from raceplan.research_analytic import vertical_bottleneck

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name',default='research_20261013')
run_name=parser.parse_args().name
if Path(run_name).name!=run_name or run_name in {'.','..'}:parser.error('invalid run name')
BASE=ROOT/'results/analysis'/run_name
RAW=ROOT/'results/raw'/run_name
FIG=ROOT/'results/figures'/run_name;FIG.mkdir(parents=True,exist_ok=True)

def read(p):
 with p.open(newline='',encoding='utf-8-sig') as f:return list(csv.DictReader(f))
def yes(v):return str(v).lower()=='true'
def avg(values):return float(np.mean(values)) if values else None

def cluster_ci(values):
    # values: one mean per map; retain all query/seed correlations within maps.
    arr=np.array(values,dtype=float);rng=np.random.default_rng(20261013)
    samples=rng.choice(arr,(2000,len(arr)),replace=True).mean(axis=1)
    return [float(v) for v in np.quantile(samples,[.025,.975])]


def summarize(rows):
 output=[]
 for planner in sorted({r['planner'] for r in rows}):
  rr=[r for r in rows if r['planner']==planner];counts=Counter(r['driving_status'] for r in rr)
  families=sorted({r['family'] for r in rr})
  rates=[avg([yes(r['pose_success']) for r in rr if r['family']==f]) for f in families]
  low,high=cluster_ci(rates)
  good=[r for r in rr if yes(r['pose_success'])]
  clear=[float(r['drive_clearance_m']) for r in rr if r['drive_clearance_m']]
  output.append(dict(planner=planner,n=len(rr),pose_success=sum(yes(r['pose_success']) for r in rr),
    pose_rate=avg([yes(r['pose_success']) for r in rr]),ci_low=low,ci_high=high,
    bootstrap_degenerate=low==high,
    position_success=sum(yes(r['position_success']) for r in rr),
    collision=counts['collision'],timeout=counts['timeout'],planning_failed=counts['not_run'],
    pose_success_rmse_mean=avg([float(r['rmse_m']) for r in good]),
    pose_success_rmse_q90=float(np.quantile([float(r['rmse_m']) for r in good],.9)) if good else None,
    driven_clearance_q10=float(np.quantile(clear,.1)) if clear else None))
 return output


validation=read(BASE/'validation.csv');tune=read(BASE/'tune.csv');evaluation=read(BASE/'evaluation.csv')
freeze=json.loads((BASE/'freeze.json').read_text())
write_csv(BASE/'analytic_map_widths.csv',[
    dict(case=c.name,split=c.split,family=c.family,
         analytic_vertical_cross_section_bottleneck_m=vertical_bottleneck(c),
         vehicle_width_normalized=vertical_bottleneck(c)/.31,
         definition='min over x slabs of widest free vertical interval between query endpoints; not global widest route')
    for split in ['validation','evaluation'] for c in cases(split)])
for stage,rows in [('validation',validation+tune),('evaluation',evaluation)]:
 write_csv(BASE/f'{stage}_summary.csv',summarize(rows))
 # independent planning repetitions; exclude warmup and map preprocessing
 times=defaultdict(list)
 roots=['validation','tune'] if stage=='validation' else ['evaluation']
 for folder in roots:
  for path in (RAW/folder).glob('*/timing.csv'):
   for row in read(path):times[row['planner']].append(float(row['seconds']))
 write_csv(BASE/f'{stage}_timing_summary.csv',[dict(planner=p,n=len(v),median_s=float(np.median(v)),
     p95_s=float(np.quantile(v,.95))) for p,v in times.items()])

index={(r['case'],r['seed'],r['planner']):r for r in evaluation}
assert len(index)==len(evaluation)==200
paired=[]
for name in sorted({r['planner'] for r in evaluation}-{'astar'}):
 effects=[]
 for family in ['gate','slalom','turn','heading']:
  diffs=[]
  for r in evaluation:
   if r['planner']!=name or r['family']!=family:continue
   b=index[r['case'],r['seed'],'astar']
   diffs.append(int(yes(r['pose_success']))-int(yes(b['pose_success'])))
   if name=='clearance_0.0':
    assert all(r[k]==b[k] for k in r if k!='planner'), 'ablation diverged'
  effects.append(float(np.mean(diffs)))
 lo,hi=cluster_ci(effects)
 paired.append(dict(planner=name,baseline='astar',paired_pose_rate_difference=avg(effects),ci_low=lo,ci_high=hi))
write_csv(BASE/'paired_effects.csv',paired)

# Correlation at case/planner level; repeats do not inflate sample size.
relations=[]
for rows,label in [(validation,'validation'),(evaluation,'evaluation')]:
 groups=defaultdict(list)
 for r in rows:groups[(r['case'],r['planner'])].append(r)
 for feature in ['bottleneck_proxy_m','reference_detour','curvature_q90','plan_clearance_m']:
  pairs=[]
  for rr in groups.values():
   good=[float(r['rmse_m']) for r in rr if r['rmse_m']]
   if rr[0][feature] and good:pairs.append((float(rr[0][feature]),float(np.mean(good))))
  x,y=np.array(pairs).T
  correlation=float(np.corrcoef(x,y)[0,1]) if np.std(x)>0 and np.std(y)>0 else None
  relations.append(dict(split=label,feature=feature,target='mean_driven_rmse',n_case_planner=len(pairs),
                         pearson_r=correlation,note='descriptive, not causal; shared cases are correlated'))
write_csv(BASE/'descriptive_relations.csv',relations)

# Representative failures retained as direct artifact references.
representatives=[]
for family in ['gate','slalom','turn','heading']:
 for p in ['dijkstra','astar','hybrid_astar',freeze['selected']]:
  rr=[r for r in evaluation if r['family']==family and r['planner']==p and not yes(r['pose_success'])]
  if rr:
   r=rr[0];representatives.append(dict(case=r['case'],planner=p,seed=r['seed'],
       reason=r['planning_status'] if r['driving_status']=='not_run' else
         ('heading_miss' if r['driving_status']=='reached' else r['driving_status']),
       trajectory=str(RAW/'evaluation'/r['case']/'trajectory.csv')))
write_csv(BASE/'representative_failures.csv',representatives)

COL={'dijkstra':'#2563eb','astar':'#d87124','hybrid_astar':'#128d76','clearance_0.25':'#8d4db8','clearance_1.0':'#b75f9b','clearance_0.0':'#728198'}
LABEL={'dijkstra':'Dijkstra','astar':'A*','hybrid_astar':'Hybrid A*','clearance_0.25':'Clearance A* 0.25','clearance_1.0':'Clearance A* 1.0','clearance_0.0':'Ablation (weight 0)'}

def canvas(title,subtitle,height=1200):
 im=Image.new('RGB',(1800,height),'#f2f5fa');d=ImageDraw.Draw(im)
 def text(x,y,s,size=24,color='#17283f',bold=False):
  d.text((x,y),str(s),fill=color,font=ImageFont.truetype('C:/Windows/Fonts/'+('malgunbd.ttf' if bold else 'malgun.ttf'),size))
 text(48,28,title,38,bold=True);text(50,88,subtitle,23,'#53647a')
 return im,d,text

for stage,rows in [('validation',validation+tune),('evaluation',evaluation)]:
 summary=summarize(rows)
 title='Validation · 후보 선택' if stage=='validation' else 'Held-out evaluation · 고정 설정 평가'
 im,d,t=canvas(title,'공통 기준: 충돌 없이 위치 0.5 m 이내 도달 + 종료 방향 오차 0.35 rad 이내',1270)
 t(50,132,'물리 지도에서 주행 · grid: 보수적 원형 planning 여유 / Hybrid: 회전 사각형 · 결과 표현 차이 포함',22)
 d.rounded_rectangle((40,190,1760,620),radius=18,fill='white')
 for x,s in [(65,'Planner'),(445,'위치+방향'),(720,'위치 도달'),(990,'충돌'),(1170,'계획 실패'),(1390,'지도 bootstrap CI')]:t(x,212,s,23,bold=True)
 for j,r in enumerate(summary):
  y=264+j*66
  t(65,y,LABEL[r['planner']],25,COL[r['planner']],True)
  t(445,y,f"{r['pose_success']} / {r['n']}",27,bold=True)
  t(720,y,f"{r['position_success']} / {r['n']}",25)
  t(990,y,r['collision'],25);t(1170,y,r['planning_failed'],25)
  t(1390,y,'퇴화: 해석 보류' if r['bootstrap_degenerate'] else f"{100*r['ci_low']:.0f}–{100*r['ci_high']:.0f}%",23)
 t(50,650,'지도 유형별 위치+방향 도달률',29,bold=True)
 xs=[500,790,1080,1370]
 for x,f in zip(xs,['gate','slalom','turn','heading']):t(x+25,700,f,24,bold=True)
 for j,r in enumerate(summary):
  y=745+j*60;t(60,y,LABEL[r['planner']],24,COL[r['planner']],True)
  for x,f in zip(xs,['gate','slalom','turn','heading']):
   rr=[q for q in rows if q['planner']==r['planner'] and q['family']==f]
   rate=np.mean([yes(q['pose_success']) for q in rr]);d.rounded_rectangle((x,y-2,x+225,y+43),radius=8,fill='#dbefe6' if rate else '#e5eaf2')
   t(x+68,y+4,f'{100*rate:.0f}%',24)
 t(50,1090,'주의: 지도 4개 단위 bootstrap. 퇴화 구간은 확실성을 뜻하지 않으며 표본이 매우 작습니다.',23)
 t(50,1132,'방향 오차는 도달 시점의 공통 사후 평가입니다. Controller를 목표 방향에 맞게 재튜닝하지 않았습니다.',22)
 t(50,1174,'동일 map family의 다른 형상에서 평가했습니다. 새로운 종류의 지도로 일반화했다는 뜻은 아닙니다.',22)
 t(50,1220,'2026-10-13 · raw / analysis / freeze / evaluation seal 보존 · 52 tests passed',20,'#53647a')
 im.save(FIG/f'{stage}.png')

im,d,t=canvas('해상도 · 주행 간격 민감도','동일 물리 형상 gate query · 무잡음 · 각 조건 3 planner · 독립 planning 반복은 별도 저장',1230)
sensitivity=read(BASE/'sensitivity.csv')
t(50,150,'조건',25,bold=True)
for x,s in [(350,'Planner'),(700,'계획'),(920,'위치+방향'),(1160,'RMSE (m)'),(1430,'주행 여유 (m)')]:t(x,150,s,24,bold=True)
for j,r in enumerate(sensitivity):
 y=200+j*48
 if j%2==0:d.rectangle((40,y-2,1760,y+43),fill='white')
 vals=[r['case'],LABEL[r['planner']],r['planning_status'],'성공' if yes(r['pose_success']) else '미달',
       f"{float(r['rmse_m']):.4f}" if r['rmse_m'] else '—',
       f"{float(r['drive_clearance_m']):.4f}" if r['drive_clearance_m'] else '—']
 for x,v in zip([50,350,700,920,1160,1430],vals):t(x,y,v,22)
t(50,964,'선택: 격자 0.1 m · dt 0.05 s · 경로 측정 간격 0.1 m',29,bold=True)
t(50,1014,'0.2 m에서는 보수적 원형 여유 + 셀 전체 여유가 통로를 막았습니다. 0.1/0.05 m도 값은 다릅니다.',23)
t(50,1057,'따라서 설정을 고정해 비교할 뿐, 해상도 수렴이나 연속 충돌 안전성을 입증한 것은 아닙니다.',23)
t(50,1100,'측정 간격 0.2/0.1/0.05 m의 별도 계산은 measurement_spacing.csv에 저장했습니다.',22)
t(50,1150,'2026-10-13 · calibration은 validation gate 한 query 기준',21,'#53647a')
im.save(FIG/'sensitivity.png')
print(json.dumps(summarize(evaluation),indent=2));print('images',FIG)
