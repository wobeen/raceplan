# 통로 폭 통제 파일럿 — 2026-10-13

## 추가한 것

기존 두 지도는 전체 구조가 달라 지도 특성의 영향을 분리하기 어려웠다.
이번에는 통로 폭만 다른 5개 validation 지도를 생성하는 모듈과 일괄 실행/
분석/이미지 보고 스크립트를 추가했다. held-out evaluation으로 사용하지 않는다.

- 지도 크기 8.0 × 4.1 m, 격자 해상도 0.1 m 고정.
- 통로 구간 x=3.0–5.0 m, 중심 y=2.05 m 고정.
- 통로 폭 1.3 / 0.9 / 0.7 / 0.5 / 0.3 m. 경계가 격자에 정확히 맞는다.
- 시작 (1.05, 1.55, 0), 목표 (6.95, 2.55, 0), planning timeout 10 s.
- baseline 차량/추종기/PID/Hybrid A* 설정과 simulation dt=0.05 s 유지.
- grid planner는 0.1 m 지도 셀을 탐색한다. Hybrid A* 내부 xy bin은 기존
  0.5 m, motion primitive 길이는 0.5 m다. 지도 해상도와 서로 다른 설정이다.
- inflation=0 m. grid planner는 점 기준, Hybrid A*는 차량 footprint 기준이다.
  동일한 차량 충돌 제약을 쓰는 planner끼리의 비교가 아니라 기존 표현 차이도
  포함한 baseline 비교이다. 실제 주행에서는 모두 같은 차량 footprint를 검사한다.
- 무잡음/잡음 2조건, simulation seed 0/1/2. 잡음 크기는 이전 파일럿과 동일.
- 0.3 m는 차량 폭 0.31 m보다 좁아 물리적으로 통과할 수 없는 음성 대조다.

이전 1 m 지도 결과와 직접 비교해 해상도의 효과를 주장하지 않는다.
통로 폭 감소와 함께 obstacle density가 증가하므로 두 효과의 독립 추정도 아니다.

## 검증과 결과

46 tests passed. 지도 폭·중심·query 고정, 장애물의 단조 증가와 통로 밖
불변성, 시작/목표 footprint 유효성을 확인했다. 세밀한 격자로 늘어난 obstacle
수를 처리하기 위해 clearance에서 거리 하한으로 불필요한 셀을 제외했으며,
회전 pose 20개에서 모든 셀을 검사한 거리와 일치하는 회귀 테스트를 추가했다.

5폭 × 2조건 × 3planner × 3seed = 90 episode 행을 저장했다.
42회 도달, 36회 충돌, 12개 계획 실패 행이다. 계획 실패에는 주행 궤적이 없다.
12개 계획 실패 행은 각 planner/지도/조건의 계획 결과를 3seed에 재사용한 것이며
12회의 독립 planning 실패 실험이 아니다. 무잡음 seed 반복 역시 독립 표본이 아니다.

| 폭 | Dijkstra | A* | Hybrid A* |
|---|---|---|---|
| 1.3 m | 3/3 도달 | 3/3 도달 | 3/3 도달 |
| 0.9 m | 3/3 도달 | 3/3 도달 | 3/3 도달 |
| 0.7 m | 3/3 주행 충돌 | 3/3 주행 충돌 | 3/3 도달 |
| 0.5 m | 3/3 주행 충돌 | 3/3 주행 충돌 | no_path, 주행 없음 |
| 0.3 m | 3/3 주행 충돌 | 3/3 주행 충돌 | no_path, 주행 없음 |

표는 각 조건의 결과이며 무잡음/잡음에서 결과 분류가 같았다.
경로는 각 폭의 zero/noise 조건에서 동일했다. 주행의 세부 오차는 seed별로 달랐다.

## 의미와 한계

1. 이번 query에서 폭 0.9→0.7 m 변화가 grid planner의 주행 성공→충돌을
   드러냈다. 점 경로의 계획 성공이 차량의 안전 주행을 보장하지 않는다.
2. 0.9 m에서 grid planner의 잡음 주행 최저 clearance는 약 1.58 cm로,
   도달 여부가 바뀌기 전에 안전 여유 감소를 관찰할 수 있었다.
3. 0.7 m에서 Hybrid A*는 도달했지만 주행 최저 clearance가 약 2.30 cm다.
   통과했다는 사실만으로 잡음/차량 조건 변화에 강건하다고 해석하지 않는다.
4. 0.5 m의 no_path는 현재 탐색 discretization/primitive 조건에서의 실패다.
   폭 자체는 차량보다 넓으며 물리적으로 경로가 존재하지 않는다는 증명은 아니다.
5. 장애물 팽창을 사용하지 않은 점 planner와 footprint planner의 차이가 크다.
   이 결과를 알고리즘의 일반적 우열로 확대하면 안 된다.
6. 단일 시작/목표 query와 세 seed만 사용했다. 실패 경계가 모든 query에
   공통이라는 뜻도, 성공률의 확률적 추정이라는 뜻도 아니다.

다음 후보는 같은 지도 묶음에서 planning collision representation을 맞추는
실험 설계다. 특히 공통 inflation을 그대로 올리면 Hybrid A*와 simulator에도
추가 margin이 적용되므로 기존 runner 옵션만 바꾸어 공정성 문제를 해결했다고
주장하지 않는다. 물리 지도와 planning용 clearance 표현을 구분하는 설계가 필요하다.

## 파일과 재현

```powershell
.venv/Scripts/python.exe -m pytest -q
# 이미 생성된 scenario family 사용
.venv/Scripts/python.exe results/run_corridor_width.py --name corridor_width_rerun
.venv/Scripts/python.exe results/render_corridor_width.py
```

생성기: `python -m raceplan.corridor_suite <새 폴더>`.
실험 스크립트는 `scenarios/corridor_width/` family를 사용한다.
렌더러는 `results/analysis/corridor_width_20261013/`와 동일 이름 raw 폴더를
읽는다. 다른 run name을 보고하려면 렌더러 입력 경로를 맞춰야 한다.

- 시나리오/지도: `scenarios/corridor_width/` (CC0-1.0)
- 원본: `results/raw/corridor_width_20261013/` (기존 Git 제외 정책)
- 분석: `results/analysis/corridor_width_20261013/` 안의 batch별 폴더
- 통합표: `width_comparison.csv`, 프로토콜: `protocol.json`
- 그림: `results/figures/corridor_width_report.png`

기존 미추적 결과와 그림은 보존했다. 자동 커밋은 하지 않았다.
