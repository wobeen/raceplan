"""Offline measurement-spacing check on a fixed stored plan, no replanning."""
import csv
import argparse
from pathlib import Path
from raceplan.research_design import Case,build
from raceplan.research_engine import write_csv
from raceplan.common import Pose2D
from raceplan.defaults import baseline_vehicle
from raceplan.metrics import path_metrics
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--name',default='research_20261013')
name=parser.parse_args().name
if Path(name).name!=name or name in {'.','..'}:parser.error('invalid run name')
base=ROOT/'results/raw'/name/'sensitivity/grid_0.1'
with (base/'paths.csv').open() as f:paths=list(csv.DictReader(f))
grid,start,goal,_=build(Case('grid_0.1','validation','gate',0,0,.1))
rows=[]
for planner in ['dijkstra','astar','hybrid_astar']:
 poses=tuple(Pose2D(float(r['x']),float(r['y']),float(r['yaw'])) for r in paths if r['planner']==planner)
 for spacing in [.2,.1,.05]:
  metrics=path_metrics(poses,grid,baseline_vehicle(),start,goal,spacing)
  rows.append(dict(planner=planner,requested_spacing=spacing,**metrics))
write_csv(ROOT/'results/analysis'/name/'measurement_spacing.csv',rows)
print('spacing check: 9 measurements saved')
