<p align="center"><a href="README.md">한국어</a> | <strong>English</strong></p>

# RacePlan

## Project Overview

RacePlan is a 2D driving simulation project that compares Dijkstra, A*, and Hybrid A* on the same physical maps and under the same vehicle conditions. It investigates how corridor width, obstacle layout, turns, and grid resolution affect path planning and vehicle driving performance.

A planned path may still lead to a collision or a stop because of the vehicle's size and steering constraints. The project therefore **evaluates planning success and actual goal arrival separately**. A run reaches the goal when the rear-axle center enters within 0.5 m of the goal position without a collision; final heading is not required.

### Planners and simulation

- **Dijkstra and A*** use grid-based planning on a map with obstacles inflated to account for vehicle size.
- **Hybrid A*** considers vehicle position, heading, and steering constraints and checks collisions against the rectangular vehicle footprint.
- Paths are driven in a shared simulator that models vehicle steering and motion. Differences in how the planners account for obstacles are considered when interpreting results.

### Experimental conditions

The baseline experiments change one map characteristic at a time while keeping the other conditions fixed:

- **Basic environment:** Open or sufficiently spacious maps to assess baseline performance.
- **Corridor width:** Progressively narrower passages to compare planning, passage, and collision outcomes.
- **Obstacle layout:** Single, consecutive, and alternating obstacles to assess detours and repeated steering.
- **Turns:** Gentle and sharp direction changes to assess steering constraints and path tracking.
- **Grid resolution:** Different cell sizes for the same physical environment to compare map representation and search cost.
- **Start and goal conditions:** Different positions and initial headings on the same map.

Driving control is compared under basic path tracking, obstacle-aware slowing and stopping, and restart and replanning after a stop. These comparisons use the same initial path; replanning count and additional computation time are recorded when the path changes. The control policy for the main map comparisons will be fixed before the experiments.

Vehicle geometry and performance, start and goal, controller settings, noise configuration, and seeds are held consistent for each comparison. Runs use multiple seeds, and search-node limits, time limits, and actual computation time are recorded. Exact condition levels and repetition counts will be decided later.

### Evaluation metrics

- Goal arrival and collision rates; planning failures, timeouts, and recovery failures
- Path length, goal arrival time, and path-planning computation time
- Minimum obstacle clearance and path-tracking error
- Stopped time, restart and replanning counts, and additional computation time

Driving times are also compared among successful runs so that early termination of a failure is not mistaken for better performance. Simulated driving time and actual planning computation time are reported separately.

### Expected outcomes and future work

The study aims to identify how map characteristics affect planner performance and how steering constraints and driving control affect goal arrival. It will also examine the relationship between grid resolution, path representation, and computation cost.

Settings will be adjusted using development maps, then held fixed for final evaluation on separate maps not used during development. Results will be presented with comparison metrics, charts, and trajectory images. These experiments are planned; validation across all listed map conditions is not yet complete.

### Results and version control

Implementation, relevant tests, experimental results, and documentation are committed in meaningful units. The repository tracks source code, map and experiment settings, summary results, and representative images. Large raw datasets are stored separately, and reproduction steps are documented.

For installation, command examples, and detailed project documentation, see the [main README](README.md#quick-start).
