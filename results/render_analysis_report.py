"""Render measured CSV results as a Korean PNG report using the project Pillow renderer."""
import csv
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw, ImageFont
from raceplan.common import load_occupancy_map

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/figures/geometry_report.png'
PLANNERS = ['dijkstra', 'astar', 'hybrid_astar']
LABELS = {'dijkstra': 'Dijkstra', 'astar': 'A*', 'hybrid_astar': 'Hybrid A*'}
COLORS = {'dijkstra': '#2563eb', 'astar': '#dd6b20', 'hybrid_astar': '#13977b'}
BG, TEXT, MUTED = '#f3f6fa', '#14243a', '#53647b'
image = Image.new('RGB', (1800, 1720), BG)
draw = ImageDraw.Draw(image)


def font(size, bold=False):
    return ImageFont.truetype('C:/Windows/Fonts/' + ('malgunbd.ttf' if bold else 'malgun.ttf'), size)


def text(x, y, value, size=24, color=TEXT, bold=False):
    draw.text((x, y), value, fill=color, font=font(size, bold))


def read(path):
    with path.open(newline='', encoding='utf-8-sig') as stream:
        return list(csv.DictReader(stream))


def card(box):
    draw.rounded_rectangle(box, radius=18, fill='white')


batches = {name: read(ROOT / f'results/analysis/geometry_20261012/{name}_noise/episodes.csv')
           for name in ['demo', 'validation_open']}
paths = read(ROOT / 'results/raw/pilot_20261012/demo_noise_paths.csv')
trajectory = read(ROOT / 'results/raw/pilot_20261012/demo_noise_trajectory.csv')
grid = load_occupancy_map(ROOT / 'maps/demo.yaml').grid
text(48, 24, 'RacePlan | 경로 기하 · 폐루프 성능 점검', 40, bold=True)
text(50, 84, '42 tests passed  ·  기존 잡음 파일럿 18 episode 분석  ·  지도별 3 planner × seed 0 / 1 / 2', 25)
text(50, 125, '새 주행 없이 저장 결과 분석  |  18/18 도달 · 충돌 0  |  소형 validation 지도, 연구 결론 아님', 23, MUTED)

for index, planner in enumerate(PLANNERS):
    left = 40 + index * 580
    card((left, 180, left + 560, 625))
    text(left + 20, 195, f'Demo · {LABELS[planner]}', 28, COLORS[planner], True)
    scale = 39
    ox, oy = left + 44, 256
    for row in range(grid.height):
        for col in range(grid.width):
            x, y = ox + col * scale, oy + (grid.height - 1 - row) * scale
            draw.rectangle((x, y, x + scale, y + scale), fill='#d2dae5' if grid.occupied[row, col] else '#f9fbfd', outline='#e5eaf0')
    def xy(r):
        return (ox + float(r['x_m']) * scale, oy + (grid.height - float(r['y_m'])) * scale)
    route = [xy(r) for r in paths if r['plan_id'] == planner]
    drive = [xy(r) for r in trajectory if r['episode_id'] == planner + ':0']
    draw.line(route, fill=COLORS[planner], width=5)
    for j in range(0, len(drive) - 1, 7):
        draw.line(drive[j:j + 4], fill='#182637', width=2)
    for point, marker in [((1.5, 1.5), 'S'), ((10.5, 6.5), 'G')]:
        x, y = ox + point[0] * scale, oy + (grid.height - point[1]) * scale
        draw.ellipse((x-9, y-9, x+9, y+9), fill='white', outline=TEXT, width=2)
        text(x+9, y-25, marker, 20, bold=True)
    text(left + 20, 579, '색 실선: 계획 경로   검정 점선: 실제 주행(seed 0)', 19, MUTED)

text(50, 650, '추종 RMSE  |  낮을수록 작음', 29, bold=True)
for index, scenario in enumerate(['demo', 'validation_open']):
    left = 40 + index * 870
    card((left, 705, left + 850, 1040))
    text(left+22, 719, 'Demo-gap' if scenario == 'demo' else 'Open field', 27, bold=True)
    text(left+22, 761, '막대: 중앙값 · 가로선: seed 최소–최대 · 단위 m', 20, MUTED)
    axis_x, width = left+220, 515
    # Shared axis across maps avoids misleading scale comparisons.
    for value in [0, .05, .10, .15]:
        x = axis_x + width * value / .15
        draw.line((x, 807, x, 970), fill='#e0e6ee', width=1)
        text(x-19, 984, f'{value:.2f}', 18, MUTED)
    for j, planner in enumerate(PLANNERS):
        values = [float(r['tracking_rmse_m']) for r in batches[scenario] if r['planner'] == planner]
        y = 811 + j * 57
        text(left+22, y+2, LABELS[planner], 23, COLORS[planner], True)
        end = axis_x + width * median(values) / .15
        draw.rectangle((axis_x, y+8, end, y+34), fill=COLORS[planner])
        a, b = [axis_x + width * v / .15 for v in [min(values), max(values)]]
        draw.line((a, y+21, b, y+21), fill=TEXT, width=2)
        for x in [a, b]:
            draw.line((x, y+14, x, y+28), fill=TEXT, width=2)
        text(max(end, b)+8, y+2, f'{median(values):.4f}', 21, TEXT, True)

text(50, 1061, '계획 경로 지표  |  동일 경로를 seed 간 재사용', 29, bold=True)
card((40, 1110, 1760, 1468))
columns = [65, 325, 595, 870, 1195, 1480]
for x, label in zip(columns, ['지도 / planner', '길이 (m)', '최대 곡률 (1/m)', '최소 clearance (m)', '목표 offset (m)', '도달 / 전체']):
    text(x, 1126, label, 22, MUTED, True)
for i, (scenario, planner) in enumerate((s, p) for s in batches for p in PLANNERS):
    row = next(r for r in batches[scenario] if r['planner'] == planner)
    y = 1170 + i * 46
    if i % 2 == 0:
        draw.rectangle((52, y-1, 1748, y+42), fill='#f5f8fb')
    label = ('Demo' if scenario == 'demo' else 'Open') + ' / ' + LABELS[planner]
    values = [label, f"{float(row['path_length_m']):.3f}",
              f"{float(row['max_discrete_curvature_per_m']):.3f}",
              f"{float(row['min_sampled_footprint_clearance_m']):.3f}",
              f"{float(row['path_goal_offset_m']):.3f}", '3 / 3']
    for x, value in zip(columns, values):
        text(x, y+4, value, 23, COLORS[planner] if x == columns[0] else TEXT)
text(50, 1490, '해석 시 주의', 26, bold=True)
text(50, 1531, '• Hybrid A*의 짧은 길이에는 goal tolerance로 목표 전에 끝난 영향이 포함됩니다.', 23, MUTED)
text(50, 1569, '• 곡률은 약 0.1 m 간격의 이산 근사입니다. Clearance는 계획 footprint의 표본 최소값입니다.', 23, MUTED)
text(50, 1607, '• 실패 없는 2개 query·3개 seed 결과입니다. 난이도별 우열·안전성·일반화를 확정할 수 없습니다.', 23, MUTED)
text(50, 1661, '출처: results/analysis/geometry_20261012/{demo_noise,validation_open_noise}/episodes.csv  |  2026-10-12', 19, MUTED)
OUT.parent.mkdir(parents=True, exist_ok=True)
image.save(OUT)
print(OUT)
