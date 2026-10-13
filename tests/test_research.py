from dataclasses import replace
import numpy as np
import pytest
from raceplan.common import OccupancyGrid,Pose2D,Path,footprint_in_collision
from raceplan.common.planning_space import circle_planning_grid
from raceplan.defaults import baseline_vehicle,baseline_simulation_config,baseline_tracker_config
from raceplan.simulator import run_episode
from raceplan.research_design import cases,build


def test_physical_map_unchanged_and_free_planning_cells_fit_rotated_vehicle():
    grid=OccupancyGrid(np.pad(np.zeros((12,18),dtype=bool),1,constant_values=True),.1)
    before=grid.occupied.copy();vehicle=baseline_vehicle();pg=circle_planning_grid(grid,vehicle)
    assert np.array_equal(before,grid.occupied)
    for cell in np.argwhere(~pg.occupied)[::7]:
        for yaw in [0,.7,1.57,2.5]:
            pose=pg.grid_to_world(tuple(cell),yaw)
            assert not footprint_in_collision(grid,pose,vehicle)


def test_reached_position_can_fail_common_heading_criterion():
    grid=OccupancyGrid(np.zeros((20,20),dtype=bool),.1)
    start=Pose2D(1,1,0);goal=Pose2D(1,1,1.57)
    result=run_episode(grid,Path((start,),0),goal,baseline_vehicle(),baseline_tracker_config(),baseline_simulation_config())
    assert result.reached
    assert result.goal_yaw_error==pytest.approx(1.57)


def test_design_split_has_four_distinct_maps_and_valid_queries():
    assert {c.name for c in cases('validation')}.isdisjoint({c.name for c in cases('evaluation')})
    for split in ['validation','evaluation']:
        signatures=set()
        for case in cases(split):
            grid,start,goal,_=build(case)
            signatures.add(grid.occupied.tobytes())
            assert not footprint_in_collision(grid,start,baseline_vehicle())
            assert not footprint_in_collision(grid,goal,baseline_vehicle())
        assert len(signatures)==4

def test_clearance_ablation_equals_astar_and_weighted_cost_never_shortcuts_obstacles():
    from raceplan.planners import AStarPlanner
    from raceplan.planners.clearance_astar import ClearanceAStar
    from raceplan.common.planning_space import circle_planning_grid
    grid,start,goal,_=build(cases('validation')[0]);pg=circle_planning_grid(grid,baseline_vehicle())
    base=AStarPlanner().plan(pg,start,goal)
    zero=ClearanceAStar(0.0).plan(pg,start,goal)
    assert zero.path==base.path
    assert zero.expanded_nodes==base.expanded_nodes
    weighted=ClearanceAStar(.25).plan(pg,start,goal)
    assert weighted.path is not None
    assert all(pg.is_free(pg.world_to_grid(p.x,p.y)) for p in weighted.path.poses)
    assert weighted.path.cost>=sum(np.hypot(b.x-a.x,b.y-a.y) for a,b in zip(weighted.path.poses,weighted.path.poses[1:]))

def test_research_resume_reuses_complete_units_and_rejects_tampering(tmp_path):
    from raceplan.research_engine import unit
    from raceplan.research_design import Case
    from raceplan.simulator import NoiseConfig
    case=Case('resume','validation','gate',0,0,.2)
    first=unit(tmp_path,case,['astar'],[0],noise=NoiseConfig(),repeats=1)
    second=unit(tmp_path,case,['astar'],[0],noise=NoiseConfig(),repeats=1)
    assert first[0]['planning_status']==second[0]['planning_status']
    with pytest.raises(ValueError,match='configuration'):
        unit(tmp_path,case,['astar'],[0,1],noise=NoiseConfig(),repeats=1)
    output=tmp_path/'resume/episodes.csv'
    output.write_text(output.read_text()+'\n')
    with pytest.raises(ValueError,match='hash'):
        unit(tmp_path,case,['astar'],[0],noise=NoiseConfig(),repeats=1)

def test_analytic_gate_bottleneck_is_resolution_independent():
    from raceplan.research_analytic import vertical_bottleneck
    from raceplan.research_design import Case
    for r in [.2,.1,.05]:
        assert vertical_bottleneck(Case('v','validation','gate',0,0,r))==pytest.approx(1.2)
        assert vertical_bottleneck(Case('e','evaluation','gate',1,0,r))==pytest.approx(1.0)
