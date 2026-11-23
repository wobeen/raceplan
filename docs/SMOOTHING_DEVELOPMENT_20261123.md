# A* 경로 후처리(충돌 검사 포함 곡률 평활화) 개발 비교 — 2026-11-23

## 질문과 범위

[급회전 제곱 비용 비교](SHARP_TURN_DEVELOPMENT_20261105.md)는 point-grid 비용항만 바꿔서는
추종 가능한 곡률과 차량 여유가 생기지 않는다고 결론냈다. 이번에는 탐색은 일반 A*로 두고,
경로를 별도로 후처리하는 가설을 시험했다. 구현은 `examples/smoothed_astar_planner.py`다.

1. A* 경로를 0.1m로 재표본화하고 첫 구간을 시작 yaw 방향으로 고정한다.
2. 100회 implicit elastic-band 반복: 후륜 축 기준점이 `target_clearance_m`보다 장애물
   셀·지도 경계에 가까우면 바깥으로 밀고(`0.5 × 부족분`), 이어서
   `100 × Σ|2차 차분|² + Σ|p − 밀린 점|²`를 시작 두 점·목표 점 고정으로 푼다.
3. 0.05m 간격·접선 yaw의 차량 footprint clearance가 0.02m 이상이고, 최대 이산 곡률이
   자전거 모델 한계 `tan(0.45)/0.33 = 1.4685/m` 이하일 때만 채택한다. 아니면 원래
   A* 경로를 그대로 반환한다. 차량·controller·시뮬레이터는 바꾸지 않았다.

변형은 목표 clearance 0.45m(`smoothed_astar`), 0.30m(`smoothed_low_clearance`),
0m 평활화만(`smoothed_no_clearance`, ablation) 세 가지다. 가중치·반복 수·목표값은
demo, validation_open, corridor_width 지도에서 기하 검사만(주행 없음) 보고 실행 전에
고정했다. 비교는 이미 공개된 `turn_aware_holdout_20261103`의 **validation 입력만**
사용한 개발 선택이며 evaluation 입력은 읽거나 실행하지 않았다. 2 family × 2 query ×
3 seed × 4 planner로 총48 episode를 한 번 실행했다. 선택 규칙은 기존과 같다:
A* 대비 도달률 무회귀가 먼저이고, 그다음 성공 RMSE와 최대 이산 곡률을 비교한다.

## 결과

| planner | 후처리 채택 case/4 | 도달/12 | 충돌 | 성공 RMSE 중앙값(m) | 성공 시간 중앙값(s) | 주행 clearance 중앙값(m) | 경로 최대 곡률 중앙값(/m) | 계획 시간 중앙값(ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A* | – | 6 | 6 | 0.07968 | 11.20 | 0.00752 | 7.7805 | 4.7 |
| 목표0.45 | 2 | 6 | 6 | 0.01126 | 11.20 | 0.10592 | 3.7363 | 134.1 |
| 목표0.30 | 4 | **12** | **0** | 0.02045 | 11.83 | 0.04826 | 0.9506 | 153.2 |
| 목표0(평활화만) | 2 | 6 | 6 | 0.00971 | 11.20 | 0.02402 | 3.6317 | 152.4 |

A* 대비 paired 결과(12쌍)는 목표0.30이 도달 승리6·패배0, 양쪽 도달6쌍의 RMSE
중앙값 −0.0698m, 완료시간 차 0s다. 목표0.45와 목표0은 승패0이며, 두 변형이 바꾼 경로는
원래 A*도 도달하던 두 case뿐이다.

Case별로 보면 A*가 세 seed 모두 충돌한 `offset_islands_q0`, `staggered_windows_q1`에서
목표0.30만 후처리를 채택해 3/3 도달했다. 같은 두 case에서 목표0.45는 footprint 여유
0.22m를 얻었지만 최대 곡률 1.547/1.537/m로 한계를 넘었고, 목표0은 footprint
clearance 0m로 거부됐다. 둘 다 A* 경로로 되돌아가 A*와 같은 충돌을 반복했다. 채택된
목표0.30 경로의 최대 곡률은 1.393/1.364/m로 한계의 93~95%이며 footprint 여유는
0.058~0.063m다. 대표 궤적은 `results/figures/smoothing_development_20261123/`에 있다.

## 판단과 한계

사전 규칙에 따라 목표0.30(`SmoothedLowClearance`)을 개발 후보로 선택한다. 이전 후보와
달리 도달률 회귀가 없고, ablation이 clearance 반발항 없이 평활화만으로는 두 실패
case를 풀지 못함을 보여 준다. 반면 목표0.45의 거부는 곡률 한계와 clearance 목표가
충돌하는 경계가 가깝다는 뜻이다.

이 결과는 일반 개선 근거가 아니다. 이미 공개된 validation 4 query에서 나온 개발
선택이고, 두 성공 전환 case 모두 곡률 한계 근처에서 채택됐다. 계획 시간은 A*보다
약30배 길다(분모: case당 1회 계획). 일반화를 주장하려면 새로 만든 지도·query로
사전 봉인한 held-out 평가가 필요하며, 이미 노출된 evaluation split은 쓰지 않는다.
기본 플래너 채택은 그 평가 전까지 보류한다.

## 재현

원본 trajectory/batch는 ignore된 `results/raw/smoothing_development_20261123/`, 집계·
채택 여부·protocol은 `results/analysis/smoothing_development_20261123/`에 있다.
채택 여부(`acceptance.csv`)는 batch에 저장되지 않으므로 같은 입력으로 결정적 재계획해
기록한다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/smoothing_development.py `
  --output-dir results/raw/smoothing_development_20261123
```
