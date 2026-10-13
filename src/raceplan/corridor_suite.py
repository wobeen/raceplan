"""Deterministic validation gate family: only the gate width changes."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
import yaml

WIDTH_CELLS = (13, 9, 7, 5, 3)
RESOLUTION = 0.1
START = [1.05, 1.55, 0.0]
GOAL = [6.95, 2.55, 0.0]


def corridor_grid(width_cells: int) -> np.ndarray:
    if width_cells not in WIDTH_CELLS:
        raise ValueError('unsupported corridor width')
    occupied = np.zeros((41, 80), dtype=bool)
    occupied[0, :] = occupied[-1, :] = True
    occupied[:, 0] = occupied[:, -1] = True
    occupied[:, 30:50] = True
    bottom = 20 - width_cells // 2
    occupied[bottom:bottom + width_cells, 30:50] = False
    return occupied


def generate(root: Path) -> Path:
    """Write an exclusive, self-contained map/query family directory."""
    root.mkdir(parents=True, exist_ok=False)
    members = []
    for width in WIDTH_CELLS:
        name = f'gate_{width:02d}'
        Image.fromarray(np.flipud(np.where(corridor_grid(width), 0, 255)).astype('uint8')).save(root / f'{name}.pgm')
        metadata = dict(image=f'{name}.pgm', resolution=RESOLUTION, origin=[0.0, 0.0, 0.0],
                        negate=0, occupied_thresh=0.65, free_thresh=0.196,
                        source='RacePlan synthetic controlled gate-width validation family', license='CC0-1.0')
        (root / f'{name}_map.yaml').write_text(yaml.safe_dump(metadata, sort_keys=False), encoding='utf-8')
        scenario = dict(name=name, map=f'{name}_map.yaml', start=START, goal=GOAL,
                        map_seed=None, simulation_seed=0, timeout_s=10.0)
        (root / f'{name}.yaml').write_text(yaml.safe_dump(scenario, sort_keys=False), encoding='utf-8')
        members.append(dict(scenario=f'{name}.yaml', width_cells=width,
                            width_m=round(width * RESOLUTION, 2),
                            feasible_width_only=width * RESOLUTION > 0.31))
    manifest = dict(family='controlled_gate_width', split='validation', resolution_m=RESOLUTION,
                    map_size_m=[8.0, 4.1], gate_x_m=[3.0, 5.0], gate_center_y_m=2.05,
                    start=START, goal=GOAL, members=members,
                    note='Width-only feasibility is necessary, not a guarantee of planning/driving success.')
    path = root / 'family.json'
    path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return path


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(generate(parser.parse_args().output))
