"""Seeded map and scenario generator: the same kind, parameters, revision and seed always give the same bytes.

Three kinds, after the research families: ``offset_islands`` (blocks alternating below and above the middle),
``staggered_windows`` (two walls, each with one window, low then high or high then low) and ``gate`` (one slab with a
centred opening whose width the seed picks). The random contract is fixed: one fresh PCG64(seed) per member and one
64-bit raw word per draw, mapped to [lo, hi] by multiply-shift; no floating-point randomness and no NumPy sampling
routine whose algorithm could change. Geometry is integer cells (0.1 m); coordinates are written from integer
millimetres.

A member is only kept when a vehicle of the default size can drive from start to goal by a conservative motion witness
(islands and windows: a lattice of 1-cell forward steps and 90-degree arcs of 0.7 m radius, each swept box padded by
0.5 m, which covers the vehicle's 0.42 m reach around the rear axle; gate: the vehicle box swept straight through the
opening). A seed that fails is recorded as rejected, never redrawn: a seed always means one map. The witness says a
path exists; it says nothing about whether a planner finds it or a tracker follows it.

Generation writes nothing outside its own new folder; family.json, written last, records everything needed to
regenerate and verify the folder byte for byte.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile

import numpy as np

REVISION = 1
SEED_LIMIT = 2**31 - 1
CELL_MM = 100
RESOLUTION = 0.1
ARC_CELLS = 7  # 0.7 m: larger than the default vehicle's minimum turning radius (0.33 m / tan 0.45 = 0.68 m)
PAD_CELLS = 5  # 0.5 m: larger than the vehicle's reach from the rear axle (hypot(0.39, 0.155) = 0.42 m)
REAR_MM, FRONT_MM, HALF_WIDTH_MM = 190, 390, 155  # default vehicle box around the rear axle (defaults.baseline_vehicle)
ISLAND_MARGIN = 20  # 2 m kept clear of islands at each end: room to line up with the start and goal headings
RNG_RULE = 'PCG64(seed).random_raw(); value = lo + ((word * (hi - lo + 1)) >> 64)'
CHECK_RULES = {'offset_islands': 'lattice: forward 1 cell, 90-degree arcs r=7 cells, swept boxes padded 5 cells, '
                                 'start and goal facing +x',
               'staggered_windows': 'lattice: forward 1 cell, 90-degree arcs r=7 cells, swept boxes padded 5 cells, '
                                    'start and goal facing +x',
               'gate': 'vehicle box (rear 190, front 390, half width 155 mm) swept straight start to goal'}
PARAMS = {  # name: (default, lowest, highest), in cells unless named otherwise
    'offset_islands': {'width': (104, 64, 128), 'height': (72, 40, 96), 'islands': (2, 2, 4),
                       'block_w': (8, 4, 10), 'block_h': (12, 4, 16)},
    'staggered_windows': {'width': (104, 64, 128), 'height': (72, 40, 96), 'wall_w': (6, 2, 8),
                          'window_h': (20, 12, 28), 'offset': (8, 4, 18), 'jitter': (3, 0, 4)},  # offset 8: research ~0.85 m stagger
    'gate': {'width': (80, 64, 128), 'height': (41, 40, 96), 'wall_w': (20, 4, 28), 'gap_min': (5, 3, 21),
             'gap_max': (13, 3, 21)},
}
MAX_SEEDS = 256


class SpecError(ValueError):
    """The kind or parameters cannot make maps (checked before any seed is used)."""


@dataclass(frozen=True)
class Spec:
    kind: str
    revision: int
    params: dict

    @property
    def params_sha256(self):
        return sha256(_json_bytes({'kind': self.kind, 'revision': self.revision, 'params': self.params})).hexdigest()

    def member_name(self, seed):
        return f'{self.kind}-r{self.revision}-p{self.params_sha256[:16]}-s{seed:010d}'


@dataclass
class Member:
    seed: int
    name: str
    files: dict = field(default_factory=dict)  # relative path -> bytes
    reason: str | None = None  # set when rejected


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode('ascii')


LINK_REPARSE_TAGS = (0xA000000C, 0xA0000003)  # IO_REPARSE_TAG_SYMLINK, _MOUNT_POINT; the stat names exist only on Windows


def is_link(path):
    """True for a symbolic link or a Windows junction at path itself (not followed). Other reparse points, such as
    OneDrive's cloud folders, are ordinary folders here."""
    info = os.lstat(path)
    return stat.S_ISLNK(info.st_mode) or getattr(info, 'st_reparse_tag', 0) in LINK_REPARSE_TAGS


def _entries(root):
    """Every file under root as a relative posix path, without following links; a linked folder is listed as an entry
    of its own. Folders that cannot be read raise (os.walk would otherwise skip them silently)."""
    found = []

    def fail(error):
        raise error
    for folder, dirs, files in os.walk(root, onerror=fail):
        base = Path(folder)
        for name in list(dirs):
            if is_link(base / name):
                dirs.remove(name)
                files.append(name)
        found += [(base / name).relative_to(root).as_posix() for name in files]
    return found


def normalize(kind, params=None, revision=REVISION):
    """Validate kind and integer parameters (defaults filled in) and check that the shape can hold them at all."""
    if kind not in PARAMS:
        raise SpecError(f'unknown kind {kind!r}; choose one of {", ".join(PARAMS)}')
    if type(revision) is not int or revision != REVISION:
        raise SpecError(f'unsupported generator revision {revision!r} (this RacePlan has revision {REVISION})')
    params = dict(params or {})
    unknown = set(params) - set(PARAMS[kind])
    if unknown:
        raise SpecError(f'unknown parameters for {kind}: {", ".join(sorted(unknown))}')
    values = {}
    for name, (default, low, high) in PARAMS[kind].items():
        value = params.get(name, default)
        if type(value) is not int or not low <= value <= high:
            raise SpecError(f'{name} must be an integer from {low} to {high}')
        values[name] = value
    _check_shape(kind, values)
    return Spec(kind, revision, values)


def _check_shape(kind, p):
    w, h = p['width'], p['height']
    if kind == 'offset_islands':
        part = (w - 2 * ISLAND_MARGIN) // p['islands']
        if part < p['block_w'] + 2 or h // 2 - 1 < p['block_h'] + 2:
            raise SpecError('the blocks do not fit their sections; use fewer or smaller islands or a larger map')
    elif kind == 'staggered_windows':
        if p['jitter'] >= p['offset']:
            raise SpecError('jitter must be smaller than offset')
        reach = p['offset'] + p['jitter']
        if h // 2 - reach - p['window_h'] // 2 < 1 or h // 2 + reach - p['window_h'] // 2 + p['window_h'] > h - 1:
            raise SpecError('a window could reach the border; use a smaller window, offset or jitter or a taller map')
        if w // 3 - p['wall_w'] // 2 <= 7 + PAD_CELLS or 2 * w // 3 - p['wall_w'] // 2 + p['wall_w'] >= w - 8 - PAD_CELLS:
            raise SpecError('a wall stands too close to the start or goal')
    else:
        if p['gap_min'] % 2 == 0 or p['gap_max'] % 2 == 0 or p['gap_min'] > p['gap_max']:
            raise SpecError('gap_min and gap_max must be odd with gap_min <= gap_max')
        left = (w - p['wall_w']) // 2
        if left <= 10 + FRONT_MM // CELL_MM + 1 or left + p['wall_w'] >= w - 11 - REAR_MM // CELL_MM - 1:
            raise SpecError('the slab stands too close to the start or goal')
        if p['gap_max'] > h - 4:
            raise SpecError('the opening is taller than the map')


class _Draw:
    def __init__(self, seed):
        self.bits = np.random.PCG64(seed)

    def __call__(self, low, high):
        word = int(self.bits.random_raw())
        return low + ((word * (high - low + 1)) >> 64)


def _layout(spec, seed):
    """(occupied rows x cols with row 0 at the bottom, obstacle boxes, start cell, goal cell)."""
    p, draw = spec.params, _Draw(seed)
    w, h = p['width'], p['height']
    occupied = np.zeros((h, w), dtype=bool)
    occupied[0, :] = occupied[-1, :] = occupied[:, 0] = occupied[:, -1] = True
    boxes = []  # [col0, row0, col1, row1), border excluded

    def block(c0, r0, c1, r1):
        occupied[r0:r1, c0:c1] = True
        boxes.append([c0, r0, c1, r1])
    if spec.kind == 'offset_islands':
        n, first = p['islands'], draw(0, 1)
        for index in range(n):
            span = w - 2 * ISLAND_MARGIN
            lo, hi = ISLAND_MARGIN + span * index // n, ISLAND_MARGIN + span * (index + 1) // n
            low_half = (first + index) % 2 == 0
            r_lo, r_hi = (1, h // 2) if low_half else (h // 2, h - 1)
            c0 = draw(lo + 1, hi - 1 - p['block_w'])
            r0 = draw(r_lo + 1, r_hi - 1 - p['block_h'])
            block(c0, r0, c0 + p['block_w'], r0 + p['block_h'])
    elif spec.kind == 'staggered_windows':
        low_first = draw(0, 1) == 0
        for index, centre in enumerate((w // 3, 2 * w // 3)):
            c0 = centre - p['wall_w'] // 2
            low = (index == 0) == low_first
            window = h // 2 + (-p['offset'] if low else p['offset']) + draw(-p['jitter'], p['jitter'])  # one word each
            w0 = window - p['window_h'] // 2
            block(c0, 1, c0 + p['wall_w'], w0)
            block(c0, w0 + p['window_h'], c0 + p['wall_w'], h - 1)
    else:
        widths = list(range(p['gap_min'], p['gap_max'] + 1, 2))
        gap = widths[draw(0, len(widths) - 1)]
        c0, g0 = (w - p['wall_w']) // 2, h // 2 - gap // 2
        block(c0, 1, c0 + p['wall_w'], g0)
        block(c0, g0 + gap, c0 + p['wall_w'], h - 1)
        return occupied, boxes, (10, h // 2), (w - 11, h // 2), {'gap_cells': gap}
    start = (7, draw(h // 4, 3 * h // 4))
    goal = (w - 8, draw(h // 4, 3 * h // 4))
    return occupied, boxes, start, goal, {}


class _Free:
    """O(1) 'is this box of cells free' from an occupancy prefix sum; anything outside the map is not free."""

    def __init__(self, occupied):
        self.h, self.w = occupied.shape
        self.sum = np.zeros((self.h + 1, self.w + 1), dtype=np.int64)
        self.sum[1:, 1:] = occupied.astype(np.int64).cumsum(0).cumsum(1)

    def cells(self, c0, r0, c1, r1):
        """Cells [c0, c1] x [r0, r1], inclusive."""
        if c0 < 0 or r0 < 0 or c1 >= self.w or r1 >= self.h or c0 > c1 or r0 > r1:
            return False
        s = self.sum
        return int(s[r1 + 1, c1 + 1] - s[r0, c1 + 1] - s[r1 + 1, c0] + s[r0, c0]) == 0

    def millimetres(self, x0, y0, x1, y1):
        """A closed box in mm: every cell it touches (edges included) must be free."""
        return self.cells(x0 // CELL_MM, y0 // CELL_MM, x1 // CELL_MM, y1 // CELL_MM)


DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))  # east, north, west, south


def _lattice_witness(free, start, goal):
    """Breadth-first search over (col, row, heading) with forward steps and 90-degree arcs, from the start cell facing
    +x to the goal cell facing +x (the scenario's poses). Each move's whole swept box, padded, must be free."""
    pad = PAD_CELLS

    def box(c0, r0, c1, r1):
        return free.cells(min(c0, c1) - pad, min(r0, r1) - pad, max(c0, c1) + pad, max(r0, r1) + pad)
    first = (start[0], start[1], 0)
    if not box(start[0], start[1], start[0], start[1]):
        return False, 0
    seen, queue = {first}, deque([first])
    while queue:
        c, r, d = queue.popleft()
        if (c, r, d) == (goal[0], goal[1], 0):
            return True, len(seen)
        dx, dy = DIRECTIONS[d]
        moves = [(c + dx, r + dy, d)]
        for turn in (1, -1):  # left, right
            nd = (d + turn) % 4
            ex, ey = DIRECTIONS[nd]
            moves.append((c + (dx + ex) * ARC_CELLS, r + (dy + ey) * ARC_CELLS, nd))
        for state in moves:
            if state not in seen and box(c, r, state[0], state[1]):
                seen.add(state)
                queue.append(state)
    return False, len(seen)


def _gate_witness(free, start, goal):
    y = start[1] * CELL_MM + CELL_MM // 2
    x0, x1 = start[0] * CELL_MM + CELL_MM // 2 - REAR_MM, goal[0] * CELL_MM + CELL_MM // 2 + FRONT_MM
    return free.millimetres(x0, y - HALF_WIDTH_MM, x1, y + HALF_WIDTH_MM)


def _mm(cells):
    value = cells * CELL_MM + CELL_MM // 2
    return f'{value // 1000}.{value % 1000:03d}'


def _endpoint_free(free, cell):
    x, y = cell[0] * CELL_MM + CELL_MM // 2, cell[1] * CELL_MM + CELL_MM // 2
    return free.millimetres(x - REAR_MM, y - HALF_WIDTH_MM, x + FRONT_MM, y + HALF_WIDTH_MM)


def build_member(spec, seed):
    """One member as files in memory (map.pgm, map.yaml, q0.yaml, geometry.json), or a rejection with its reason."""
    if type(seed) is not int or not 0 <= seed <= SEED_LIMIT:
        raise SpecError(f'seed must be an integer from 0 to {SEED_LIMIT}')
    name = spec.member_name(seed)
    occupied, boxes, start, goal, extra = _layout(spec, seed)
    free = _Free(occupied)
    if not (_endpoint_free(free, start) and _endpoint_free(free, goal)):
        return Member(seed, name, reason='endpoint_blocked')
    if spec.kind == 'gate':
        ok, explored = _gate_witness(free, start, goal), None
        if not ok:
            return Member(seed, name, reason='gate_clearance')
    else:
        ok, explored = _lattice_witness(free, start, goal)
        if not ok:
            return Member(seed, name, reason='no_motion_witness')
    h, w = occupied.shape
    pgm = f'P5\n{w} {h}\n255\n'.encode('ascii') + np.flipud(np.where(occupied, 0, 255)).astype(np.uint8).tobytes()
    map_yaml = ('image: map.pgm\nresolution: 0.1\norigin: [0.0, 0.0, 0.0]\nnegate: 0\noccupied_thresh: 0.65\n'
                'free_thresh: 0.196\n'
                f'source: RacePlan seed map generator, {spec.kind} revision {spec.revision}, seed {seed}\n'
                'license: CC0-1.0\n')
    scenario = (f'name: {name}\nmap: map.yaml\nstart: [{_mm(start[0])}, {_mm(start[1])}, 0.0]\n'
                f'goal: [{_mm(goal[0])}, {_mm(goal[1])}, 0.0]\nmap_seed: {seed}\nsimulation_seed: 0\ntimeout_s: 10.0\n')
    geometry = {'kind': spec.kind, 'revision': spec.revision, 'params': spec.params, 'seed': seed,
                'size_cells': [w, h], 'cell_mm': CELL_MM, 'border_cells': 1, 'obstacles_cells': boxes,
                'start_cell': list(start), 'goal_cell': list(goal), 'witness': CHECK_RULES[spec.kind],
                **({'witness_states': explored} if explored is not None else {}), **extra}
    return Member(seed, name, files={'map.pgm': pgm, 'map.yaml': map_yaml.encode('ascii'),
                                     'q0.yaml': scenario.encode('ascii'), 'geometry.json': _json_bytes(geometry)})


def _suite_yaml(members):
    lines = ['version: 1', 'cases:']
    lines += [f'  - id: {member.name}\n    scenario: members/{member.name}/q0.yaml' for member in members]
    return ('\n'.join(lines) + '\n').encode('ascii')


def build_family(spec, first, last):
    """Members of seeds first..last (inclusive) and the family record; nothing is written."""
    if type(first) is not int or type(last) is not int or not 0 <= first <= last <= SEED_LIMIT:
        raise SpecError(f'seeds must be integers with 0 <= first <= last <= {SEED_LIMIT}')
    if last - first + 1 > MAX_SEEDS:
        raise SpecError(f'at most {MAX_SEEDS} seeds at once')
    members = [build_member(spec, seed) for seed in range(first, last + 1)]
    kept = [member for member in members if member.reason is None]
    suite = _suite_yaml(kept) if len(kept) == len(members) else None
    record = {'schema_version': 1, 'generator': 'raceplan.seed_maps', 'kind': spec.kind, 'revision': spec.revision,
              'params': spec.params, 'params_sha256': spec.params_sha256, 'rng': RNG_RULE, 'check': CHECK_RULES[spec.kind],
              'seeds': [first, last],
              'members': [{'seed': member.seed, 'name': member.name, 'status': 'rejected', 'reason': member.reason}
                          if member.reason else
                          {'seed': member.seed, 'name': member.name, 'status': 'ok',
                           'files': {f'members/{member.name}/{name}': sha256(data).hexdigest()
                                     for name, data in sorted(member.files.items())}} for member in members],
              'suite': {'file': 'suite.yaml', 'sha256': sha256(suite).hexdigest()} if suite else None}
    return members, suite, record


def write_family(spec, first, last, out):
    """Generate into a new folder (refused if it exists); family.json is published last and atomically, so a folder
    without it is incomplete. Returns the family record."""
    out = Path(out)
    members, suite, record = build_family(spec, first, last)
    out.mkdir(parents=True, exist_ok=False)
    for member in members:
        if member.reason:
            continue
        folder = out / 'members' / member.name
        folder.mkdir(parents=True)
        for name, data in member.files.items():
            (folder / name).write_bytes(data)
    if suite:
        (out / 'suite.yaml').write_bytes(suite)
    handle, temporary = tempfile.mkstemp(dir=out, prefix='.family-', suffix='.tmp')
    with os.fdopen(handle, 'wb') as stream:
        stream.write(_json_bytes(record))
    os.replace(temporary, out / 'family.json')
    return record


def verify_family(root):
    """Regenerate a written family from its record and compare: family.json and every file byte for byte, same
    rejections, no other files. Returns a list of problems (empty when it verifies); unreadable files are problems."""
    root = Path(root)
    try:
        raw = (root / 'family.json').read_bytes()
        record = json.loads(raw.decode('ascii'))
        spec = normalize(record['kind'], record['params'], record['revision'])
        first, last = record['seeds']
        members, suite, expected = build_family(spec, first, last)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as exc:  # RecursionError: absurdly nested JSON
        return [f'cannot verify: {exc}']
    problems = [] if raw == _json_bytes(expected) else ['family.json differs from a fresh generation']
    wanted = {f'members/{member.name}/{name}': data for member in members if not member.reason
              for name, data in member.files.items()}
    if suite:
        wanted['suite.yaml'] = suite
    try:
        present = set(_entries(root)) - {'family.json'}
    except OSError as exc:
        return problems + [f'cannot list the folder: {exc}']
    for name in sorted(present - set(wanted)):
        problems.append(f'unexpected file {name}')
    for name, data in sorted(wanted.items()):
        path = root / name
        try:
            if not path.is_file():
                problems.append(f'missing file {name}')
            elif path.read_bytes() != data:
                problems.append(f'file differs from a fresh generation: {name}')
        except OSError as exc:
            problems.append(f'cannot read {name}: {exc}')
    return problems
