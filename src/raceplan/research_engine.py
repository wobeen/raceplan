"""Resumable research batch units with physical-map simulation and complete artifacts."""
from dataclasses import asdict, replace
from pathlib import Path
import csv
import hashlib
import json
import platform
import shutil
import numpy as np
from raceplan.common import Pose2D
from raceplan.common.planning_space import circle_planning_grid,enclosing_radius
from raceplan.defaults import baseline_vehicle,baseline_tracker_config,baseline_simulation_config,baseline_hybrid_astar
from raceplan.planners import DijkstraPlanner,AStarPlanner
from raceplan.simulator import NoiseConfig,run_episode
from raceplan.metrics import Clearance,path_metrics,resample
from raceplan.research_design import save_case,build
from raceplan.research_features import descriptors

BASELINES=['dijkstra','astar','hybrid_astar']
NOISE=NoiseConfig(.02,.01,.01,.01,.02)


def dump(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write_csv(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def planner(name):
    if name=='dijkstra':return DijkstraPlanner()
    if name=='astar':return AStarPlanner()
    if name=='hybrid_astar':return baseline_hybrid_astar()
    from raceplan.planners.clearance_astar import ClearanceAStar
    return ClearanceAStar(float(name.split('_')[-1]))


def unit(root,case,names,seeds,dt=.05,noise=NOISE,repeats=3,timeout=3.0,spacing=.1):
    folder=root/case.name
    config=dict(case=asdict(case),planners=names,seeds=list(seeds),dt=dt,noise=asdict(noise),
                timing_repeats=repeats,timeout=timeout,spacing=spacing,
                vehicle=asdict(baseline_vehicle()),tracker=asdict(baseline_tracker_config()),
                simulation=asdict(replace(baseline_simulation_config(),dt=dt)),
                pose_success_yaw_rad=.35,collision_grid='physical',
                grid_planning='enclosing rear-axle disk plus cell half-diagonal',
                hybrid_config=asdict(baseline_hybrid_astar().config),
                python=platform.python_version(),numpy=np.__version__)
    package=Path(__file__).parent
    source_files=[p for p in package.rglob('*.py')
                  if p.name not in {'clearance_astar.py'} and not p.name.startswith('research_')]
    source_files += [package/n for n in ('research_engine.py','research_design.py','research_features.py')]
    if any(n.startswith('clearance_') for n in names):
        source_files.append(package/'planners/clearance_astar.py')
    config['source_sha256']={str(p.relative_to(package)):digest(p) for p in sorted(source_files)}
    if (folder/'complete.json').exists():
        done=json.loads((folder/'complete.json').read_text())
        if done['config']!=config:raise ValueError('resume configuration mismatch')
        for name,value in done['artifact_sha256'].items():
            if digest(folder/name)!=value:raise ValueError('resume artifact hash mismatch')
        with (folder/'episodes.csv').open() as f:return list(csv.DictReader(f))
    if folder.exists():
        # Never destroy interrupted outputs; keep a numbered attempt alongside.
        attempt=1
        while folder.with_name(folder.name+f'.interrupted{attempt}').exists():attempt+=1
        folder.rename(folder.with_name(folder.name+f'.interrupted{attempt}'))
    grid,start,goal=save_case(case,folder)
    vehicle=baseline_vehicle();pg=circle_planning_grid(grid,vehicle)
    dump(folder/'configuration.json',config)
    desc=descriptors(grid,start,goal,vehicle);dump(folder/'features.json',desc)
    checker=Clearance(grid);rows=[];timing=[];paths=[];samples=[]
    for name in names:
        algorithm=planner(name);planning_grid=grid if name=='hybrid_astar' else pg
        # Explicit warmup, followed by independent deterministic planning repetitions.
        algorithm.plan(planning_grid,start,goal,timeout_s=timeout)
        plans=[algorithm.plan(planning_grid,start,goal,timeout_s=timeout) for _ in range(repeats)]
        planned=plans[0]
        for index,plan in enumerate(plans):
            timing.append(dict(planner=name,repeat=index,status=plan.status.value,
                               seconds=plan.planning_time_s,expanded_nodes=plan.expanded_nodes))
        metrics={}
        if planned.path:
            metrics=path_metrics(planned.path.poses,grid,vehicle,start,goal,spacing)
            xy=resample(planned.path.poses,spacing)
            headings=np.arctan2(np.diff([p.y for p in xy]),np.diff([p.x for p in xy]))
            changes=np.abs((np.diff(headings)+np.pi)%(2*np.pi)-np.pi)
            metrics['curvature_q90']=float(np.quantile(changes,.9)/metrics['sample_spacing_m']) if len(changes) else None
            for i,p in enumerate(planned.path.poses):paths.append(dict(planner=name,index=i,x=p.x,y=p.y,yaw=p.yaw))
        for seed in seeds:
            row=dict(case=case.name,split=case.split,family=case.family,query=case.query,
                planner=name,seed=seed,planning_status=planned.status.value,driving_status='not_run',
                position_success=False,pose_success=False,collision=False,rmse_m=None,
                max_error_m=None,time_s=None,goal_distance_m=None,goal_yaw_error_rad=None,
                steering_variation=None,steering_saturation=None,drive_clearance_m=None,
                path_length_m=metrics.get('path_length_m'),curvature_q90=metrics.get('curvature_q90'),
                plan_clearance_m=metrics.get('min_sampled_footprint_clearance_m'),
                density=desc['obstacle_density'],bottleneck_proxy_m=desc['widest_grid_disk_diameter_m'],
                reference_detour=desc['reference_detour'])
            if planned.path:
                result=run_episode(grid,planned.path,goal,vehicle,baseline_tracker_config(),
                    replace(baseline_simulation_config(),dt=dt),initial_pose=start,simulation_seed=seed,noise=noise)
                clearances=[checker.footprint(s.state.pose,vehicle) for s in result.samples]
                row.update(driving_status=result.status.value,position_success=result.reached,
                    pose_success=result.reached and result.goal_yaw_error<=.35,collision=result.collided,
                    rmse_m=result.tracking_rmse,max_error_m=result.max_tracking_error,time_s=result.completion_time_s,
                    goal_distance_m=result.goal_distance,goal_yaw_error_rad=result.goal_yaw_error,
                    steering_variation=result.steering_total_variation,
                    steering_saturation=result.steering_saturation_fraction,drive_clearance_m=min(clearances))
                for i,(s,c) in enumerate(zip(result.samples,clearances)):
                    p=s.state.pose
                    samples.append(dict(planner=name,seed=seed,step=i,time=s.time_s,x=p.x,y=p.y,yaw=p.yaw,
                        speed=s.state.speed,acceleration=s.acceleration,steering=s.steering_angle,
                        error=s.tracking_error,clearance=c))
            rows.append(row)
    write_csv(folder/'episodes.csv',rows);write_csv(folder/'timing.csv',timing)
    write_csv(folder/'paths.csv',paths);write_csv(folder/'trajectory.csv',samples)
    artifacts={p.name:digest(p) for p in folder.iterdir() if p.is_file()}
    dump(folder/'complete.json',dict(config=config,artifact_sha256=artifacts))
    print(f'{case.name}: {len(rows)} episodes stored',flush=True)
    return rows
