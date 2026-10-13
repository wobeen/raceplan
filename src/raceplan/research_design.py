"""Predeclared small synthetic research suite; evaluation outcomes stay sealed until freeze."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import numpy as np
from PIL import Image
import yaml
from raceplan.common import OccupancyGrid, Pose2D


@dataclass(frozen=True)
class Case:
    name: str
    split: str
    family: str
    variant: int
    query: int
    resolution: float = .1


def cases(split):
    variants = [0] if split == 'validation' else [1]
    return [Case(f'{split}_{family}_{variant}_q{query}', split, family, variant, query)
            for family in ['gate', 'slalom', 'turn', 'heading']
            for variant in variants for query in [0, 1]]


def build(case):
    r=case.resolution
    # Geometry boundaries are in metres; occupied cells intersect rectangle interiors.
    size=(8.,6.)
    rectangles=[(0,0,8,.2),(0,5.8,8,6), (0,0,.2,6), (7.8,0,8,6)]
    offset = .2*case.variant
    if case.family == 'gate':
        width=1.2 if case.variant==0 else 1.0
        rectangles += [(3, .2,5,3-width/2),(3,3+width/2,5,5.8)]
        start, goal=(1.3,2.5,0),(6.7,3.5,0)
    elif case.family == 'slalom':
        rectangles += [(2.4,.2,2.8,2.8+offset),(4.8,3.2-offset,5.2,5.8)]
        start, goal=(1.3,2.,0),(6.7,4.,0)
    elif case.family == 'turn':
        rectangles += [(3.,.2,4.4,3.6+offset)]
        start, goal=(1.3,2.,0),(6.7,2.,0)
    else:
        rectangles += [(3.,2.,4.,3.+offset)]
        start, goal=(1.3,1.5,0),(6.7,4.5,1.5707963267948966)
    if case.query:
        start=(start[0],start[1]+.2,0)
        goal=(goal[0],goal[1]-.2,goal[2])
    ncols,nrows=round(size[0]/r),round(size[1]/r)
    yy,xx=np.indices((nrows,ncols)); left=xx*r; bottom=yy*r
    occupied=np.zeros((nrows,ncols),dtype=bool)
    for x0,y0,x1,y1 in rectangles:
        occupied |= (left < x1-1e-9)&(left+r>x0+1e-9)&(bottom<y1-1e-9)&(bottom+r>y0+1e-9)
    return OccupancyGrid(occupied,r),Pose2D(*start),Pose2D(*goal),rectangles


def save_case(case, folder):
    folder.mkdir(parents=True,exist_ok=False)
    grid,start,goal,rectangles=build(case)
    Image.fromarray(np.flipud(np.where(grid.occupied,0,255)).astype('uint8')).save(folder/'map.pgm')
    (folder/'map.yaml').write_text(yaml.safe_dump(dict(image='map.pgm',resolution=case.resolution,
        origin=[0.,0.,0.],source='RacePlan synthetic research suite',license='CC0-1.0')))
    (folder/'design.json').write_text(json.dumps(dict(case=asdict(case),start=asdict(start),
        goal=asdict(goal),rectangles_m=rectangles),indent=2))
    return grid,start,goal
