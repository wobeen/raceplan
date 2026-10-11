# Hybrid A* design decisions

Updated: 2026-10-12

## Vehicle reference and geometry

`Pose2D` represents the rear-axle centre. The vehicle footprint is a rectangle
defined by wheelbase, total length, total width, and the longitudinal offset
from the rear axle to the rectangle centre. This makes the kinematic reference
explicit instead of assuming that the pose is the geometric centre.

## Motion primitives

Primitives use the kinematic bicycle model with constant steering over a fixed
travel distance. Integration is exact for each constant-curvature segment and
returns samples no farther apart than the configured collision-check distance.

The steering set contains an odd number of evenly spaced values so that zero
steering is always present. Forward-only and forward/reverse primitive sets are
both supported. The initial Hybrid A* search can start forward-only; enabling
reverse later does not require changing the kinematic implementation.

## Collision convention

The vehicle rectangle is checked against occupied grid-cell rectangles using a
separating-axis intersection test. Every sampled pose of a primitive is
checked, including the starting pose. Touching an occupied cell or leaving the
known map is treated as collision.

This footprint check is specific to Hybrid A*. Grid planners continue to use a
shared inflated map. Experiments must record the inflation radius and vehicle
dimensions so the difference between these collision representations is
visible rather than silently treated as identical.

## Implemented search

- continuous `(x, y, yaw)` poses with discretized visited-cost bookkeeping;
- Euclidean distance guidance and deterministic insertion-order tie-breaking;
- separate goal position and heading tolerances;
- continuous primitive-sample reconstruction into a `Path`;
- standard timeout, no-path, and invalid-pose `PlannerResult` values;
- successful checks on an open map and the repository obstacle demo.

The current cost is travelled distance only. Reverse is supported by the
primitive layer but disabled in the baseline comparison. Steering-change,
reverse, clearance, and curvature penalties are intentionally deferred until
the required three-planner comparison pipeline works.

The development comparison is not yet a formal apples-to-apples path-quality
measurement: grid paths terminate at the goal-cell centre, while Hybrid A*
terminates inside a configured goal-pose tolerance. Continuous Hybrid A*
samples are also denser than grid waypoints. Official metrics must resample
paths consistently and record final pose error.
