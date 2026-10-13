"""Exact axis-aligned cross-section widths for this rectangle-based map design.

This is an analytic map descriptor, not an arbitrary-orientation widest-path
claim. Free intervals are measured in continuous metres, independent of raster.
"""
from raceplan.research_design import build


def vertical_bottleneck(case):
    _,start,goal,rectangles=build(case)
    left,right=sorted((start.x,goal.x))
    cuts=sorted({left,right}|{x for rect in rectangles for x in (rect[0],rect[2]) if left<x<right})
    sections=[]
    for a,b in zip(cuts,cuts[1:]):
        x=(a+b)/2
        intervals=sorted((r[1],r[3]) for r in rectangles if r[0]<x<r[2])
        end=0.;largest=0.
        for lo,hi in intervals:
            largest=max(largest,lo-end)
            end=max(end,hi)
        largest=max(largest,6.-end)
        sections.append(largest)
    return min(sections)
