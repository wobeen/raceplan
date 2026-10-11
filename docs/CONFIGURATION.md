# Configuration

## Scenario YAML

Each scenario is one strict YAML mapping:

```yaml
name: demo-gap
map: ../maps/demo.yaml
start: [1.5, 1.5, 0.0]
goal: [10.5, 6.5, 0.0]
seed: 0
timeout_s: 10.0
```

Paths are resolved relative to the scenario file. Poses use metres and radians.
Unknown keys are rejected so configuration typos cannot silently alter an
experiment. The seed is recorded even when a deterministic planner does not use
randomness; later simulation noise will use it.

## Map YAML

Map files follow the ROS map-server grayscale convention and add mandatory
provenance:

```yaml
image: demo.pgm
resolution: 1.0
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
source: RacePlan synthetic demo map
license: CC0-1.0
```

The image may use any grayscale format supported by Pillow. Image rows are
flipped during loading so grid rows increase with world y. Rotated origins are
currently rejected. Unknown pixels are occupied by default, which is the safer
policy for global planning.

## Inflation

`inflate_obstacles(grid, radius_m)` applies one common circular clearance rule
before planners run. The radius should combine the agreed vehicle footprint
approximation and experiment clearance. Raw and inflated grids must not both
encode the same clearance, to avoid accidental double inflation.
