"""Staged reproducible research pipeline. Evaluation requires a frozen validation decision."""
import argparse
from dataclasses import replace,asdict
from pathlib import Path
import json
import csv
import hashlib
from raceplan.research_design import Case,cases
from raceplan.research_engine import unit,BASELINES,NOISE,dump,write_csv
from raceplan.simulator import NoiseConfig

ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('stage',choices=['sensitivity','validation','tune','evaluation'])
 p.add_argument('--name',default='research_20261013')
 a=p.parse_args()
 if Path(a.name).name!=a.name or a.name in {'.','..'}:p.error('invalid run name')
 raw=ROOT/'results/raw'/a.name;report=ROOT/'results/analysis'/a.name
 raw.mkdir(parents=True,exist_ok=True);report.mkdir(parents=True,exist_ok=True)
 rows=[]
 if a.stage=='sensitivity':
  for r in [.2,.1,.05]:
   c=Case(f'grid_{r}','validation','gate',0,0,r)
   rows+=unit(raw/'sensitivity',c,BASELINES,[0],noise=NoiseConfig(),repeats=3)
  for dt in [.1,.025]:
   c=Case(f'dt_{dt}','validation','gate',0,0,.1)
   rows+=unit(raw/'sensitivity',c,BASELINES,[0],dt=dt,noise=NoiseConfig(),repeats=3)
 elif a.stage=='validation':
  for c in cases('validation'):
   rows+=unit(raw/'validation',c,BASELINES,[0,1,2],repeats=3)
 elif a.stage=='tune':
  if not (report/'validation.csv').exists():raise ValueError('run baseline validation first')
  if (report/'freeze.json').exists():raise ValueError('decision already frozen')
  for c in cases('validation'):
   rows+=unit(raw/'tune',c,['clearance_0.25','clearance_1.0'],[0,1,2],repeats=3)
  with (report/'validation.csv').open() as f:base=list(csv.DictReader(f))
  candidates=base+[dict(r) for r in rows]
  def truth(v):return str(v).lower()=='true'
  scores={}
  for name in ['astar','clearance_0.25','clearance_1.0']:
   rr=[r for r in candidates if r['planner']==name]
   values=[float(r['rmse_m']) for r in rr if truth(r['pose_success'])]
   # Predeclared lexicographic objective; no held-out information enters.
   scores[name]=[sum(truth(r['pose_success']) for r in rr),
                 -sum(truth(r['collision']) for r in rr),
                 -sum(values)/len(values) if values else -1e9]
  selected=max(['clearance_0.25','clearance_1.0'],key=lambda n:(scores[n],-['clearance_0.25','clearance_1.0'].index(n)))
  dump(report/'freeze.json',dict(selected=selected,scores=scores,
      outperformed_baseline_on_validation=scores[selected]>scores['astar'],
      rule='maximize pose successes, then minimize collisions, then successful mean RMSE; ties prefer lower weight',
      resolution=.1,dt=.05,spacing=.1,goal_position=.5,goal_yaw=.35,
      validation_seeds=[0,1,2],evaluation_seeds=[3,4,5,6,7],
      baseline='astar',ablation='clearance_0.0',evaluation_cases=[asdict(c) for c in cases('evaluation')]))
 else:
  freeze_path=report/'freeze.json'
  freeze=json.loads(freeze_path.read_text())
  frozen_hash=hashlib.sha256(freeze_path.read_bytes()).hexdigest()
  seal=report/'evaluation_seal.json'
  if seal.exists():
   if json.loads(seal.read_text())['freeze_sha256']!=frozen_hash:raise ValueError('frozen decision changed after evaluation started')
  else:dump(seal,dict(freeze_sha256=frozen_hash,rule='No retuning after this seal'))
  # Always retain the stronger clearance candidate for a transparent negative-result comparison.
  names=BASELINES+['clearance_0.0']
  if freeze['selected'] not in names:names.append(freeze['selected'])
  for c in cases('evaluation'):
   rows+=unit(raw/'evaluation',c,names,freeze['evaluation_seeds'],dt=freeze['dt'],repeats=5)
 write_csv(report/f'{a.stage}.csv',rows)
 print('stage complete',a.stage,report,flush=True)

if __name__=='__main__':main()
