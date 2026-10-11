# Maps

Every map must include a ROS-style YAML sidecar with these fields:

- `image`, `resolution`, and `origin: [x, y, yaw]`
- `negate`, `occupied_thresh`, and `free_thresh`
- non-empty `source` and `license` provenance

RacePlan currently supports zero-yaw origins. Unknown cells are treated as
occupied by default. `demo.pgm` is a synthetic CC0 fixture created for this
project and is not an evaluation map.
