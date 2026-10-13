# 실제 주행 clearance — 2026-10-13

## 추가 기능과 검증

기존 분석기에 기록된 실제 차량 pose/yaw의 footprint clearance를 추가했다.
계획 경로의 보간 yaw가 아니라 trajectory CSV의 실제 yaw를 사용한다.
시작·종료·충돌 시점을 포함한 모든 기록을 처리하며 표본 사이를 보간하지 않는다.
기존 raw 데이터·이전 분석 결과는 보존했다.

- 44 tests passed. 회전된 차량의 거리, 접촉/영역 이탈 0, 초기 충돌 집계,
  seed 짝비교 및 잘린 trajectory 거부를 확인했다.
- 기존 두 지도 noise batch의 18 episode를 재분석했다. 새 주행 실험은 아니다.
- `clearance_samples.csv`: episode/step/time/실제 pose/clearance 저장.
- `episodes.csv`: 실제 최소 clearance, 차량 폭 정규화 값, 최초 최소 시각,
  실제 최소 − 계획 최소의 기술적 차이 저장.
- `planners.csv`: 주행한 모든 episode(충돌·timeout 포함)의 최소값, Q10, 중앙값.
- `paired.csv`: 둘 다 주행했을 때만 같은 seed의 실제 최소 clearance 차이 저장.
  기존 RMSE 등의 차이는 둘 다 도달한 조건을 유지한다.
- analysis schema는 2로 변경하고 trajectory 파일 hash를 provenance에 추가했다.
- 미지 episode, 계획 실패에 붙은 trajectory, 누락/중복 step, 비정상 시간,
  simulation dt·종료 시간 불일치는 분석 결과 생성 전에 거부한다.

## 결과

Demo에서 세 seed 중 가장 작은 실제 clearance:

| Planner | 계획 최소 (cm) | 실제 주행 최저 (cm) | seed / 발생 시각 |
|---|---:|---:|---|
| Dijkstra | 11.00 | 27.11 | 1 / 6.10 s |
| A* | 11.00 | 28.28 | 0 / 6.00 s |
| Hybrid A* | 5.30 | 1.42 | 0 / 6.95 s |

Hybrid A*의 실제 최소값은 seed별 1.42–1.72 cm였다. 이전 보고에서 RMSE가
가장 낮았지만 장애물 여유 공간은 더 작다. 추종 정확도와 안전 여유는 각각
측정해야 한다는 사례다. 해당 잡음/차량/지도 조건에서의 관찰이며 충돌 확률을
추정하거나 다른 지도에 일반화할 수 없다.

Open에서는 모든 planner의 실제 최소가 seed별 33.77 / 29.66 / 28.77 cm로
일치했고 모두 초기 상태(t=0)에서 발생했다. 전체 최소값 하나는 공통 출발
조건에 지배될 수 있으므로 경로 중간의 특성을 항상 구분하지 못한다.

계획과 주행은 종료 위치, 방향 및 표본 간격이 다르다. 특히 controller는
goal tolerance 안에서 종료하므로 목표 waypoint까지 주행하지 않는다.
따라서 Dijkstra/A*의 실제 최소가 계획 최소보다 크다는 결과를 controller의
안전성 개선 효과라고 단정하지 않는다. 두 경로의 최소 발생 위치도 다를 수 있다.

## 한계와 다음 한 가지

0.05초 기록 시점의 unsigned 거리이며 표본 사이 연속 swept collision의
부재를 보장하지 않는다. 0은 접촉·교차·맵 밖을 포함하며 침투 깊이를 뜻하지 않는다.
실패의 시점·종료 길이 차이도 있으므로 clearance만으로 전체 planner를 순위화하지 않는다.

다음에는 **통로 폭만 단계적으로 바뀌는 validation 시나리오 묶음**을 추가해
여유 공간 축소가 실제 충돌·timeout으로 이어지는 조건을 확인할 계획이다.
다른 차량·controller·seed 조건은 고정한다. 이번 작업에서는 해당 실험을 추가하지 않았다.

## 재현

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m raceplan.analyze results/raw/pilot_20261012/demo_noise.csv --output-dir results/analysis/driving_clearance_20261013/demo
.venv/Scripts/python.exe -m raceplan.analyze results/raw/pilot_20261012/validation_open_noise.csv --output-dir results/analysis/driving_clearance_20261013/open
.venv/Scripts/python.exe results/render_driving_clearance.py
```

분석 명령은 기존 출력 폴더를 거부하므로 재실행 시 새 폴더를 지정한다.
렌더러는 위 두 분석 폴더를 입력으로 사용하며 그림 파일은 다시 저장한다.
이미지: `results/figures/driving_clearance_report.png`.
