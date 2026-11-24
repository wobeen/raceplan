# A* 경로 후처리 후보 신규 지도 held-out 사전 프로토콜 — 2026-11-23

## 질문과 고정 후보

[개발 비교](SMOOTHING_DEVELOPMENT_20261123.md)에서 선택한 `SmoothedLowClearance`
(목표 clearance 0.30m, 평활화 가중치100, 반복100, 반발 step0.5, footprint 여유0.02m,
간격0.1m, 곡률 한계1.4685/m)가 공개 validation 밖의 새 지도에서도 A*보다 도달률을
높이는지 확인한다. 후보와 ablation(`SmoothedNoClearance`, 목표0)의 코드·설정은 개발
비교 커밋 그대로이며 실행 전 runner가 설정값을 확인한다. 이 평가 결과로 후보를 다시
고르거나 파라미터를 바꾸지 않는다. 후보 선택이 끝났으므로 validation split 없이
evaluation 한 split만 한 번 실행한다.

## 실행 전 고정한 지도·query·예산

규모는 **3family × 2지도 × 2query × 3seed × 5planner = 180 episode**다. Planner는
Dijkstra, A*, Hybrid A*, 후보, ablation이다. 지도는 기존 holdout과 같은 10.4×7.2m,
해상도0.2m, 0.2m 외벽이며 내부 형상은 새로 정했다. `results/smoothing_holdout.py`의
`design` 함수가 결과를 보기 전에 아래 형상을 고정한다.

| family | 지도 a 내부 장애물(m) | 지도 b 내부 장애물(m) |
|---|---|---|
| staggered_windows | x3.4–4.0 벽의 y1.0–3.0 창, x6.8–7.4 벽의 y4.4–6.4 창 | x2.8–3.4 벽의 y3.8–5.8 창, x6.4–7.0 벽의 y1.0–3.2 창 |
| offset_islands | (2.4,1.0)–(3.8,3.0), (4.8,3.8)–(6.2,5.8), (7.2,1.4)–(8.6,3.4) | (2.6,4.0)–(4.0,6.2), (5.0,1.0)–(6.4,3.2), (7.4,3.8)–(8.8,5.8) |
| slalom_walls | 아래 벽 x3.4–3.8/y0.2–4.4, 위 벽 x6.6–7.0/y2.8–7.0 | 위 벽 x3.0–3.4/y2.6–7.0, 아래 벽 x6.8–7.2/y0.2–4.6 |

`slalom_walls`는 이전 연구에 없던 family다. 나머지 두 family는 같은 구조의 새 형상이므로
새 family 일반화로 부르지 않는다. 모든 지도의 query는 (1.2,1.6)→(9.2,5.6),
(1.2,5.6)→(9.2,1.6)이고 yaw는 0rad다. Seed는 이전 연구와 겹치지 않는 31/32/33이다.
잡음은 위치0.02m, 초기 yaw0.02rad, steering0.01rad, speed measurement0.02m/s다.

계획은 query/planner당 1회(총60회), timeout2s, simulation30s/dt0.05s다. inflation0의
원본 물리 지도를 계획과 주행에 공통 사용하고 guard/recovery는 비활성이다. 성공은 충돌
없이 0.5m 이내 진입이며 yaw는 참고값이다. 후처리 채택 여부는 batch에 저장되지 않으므로
실행 후 같은 입력으로 후보·ablation을 결정적으로 재계획해 기록하고, 재계획 경로 길이가
저장된 경로 길이와 같은지 확인한다. 이 감사는 결과 집계를 바꾸지 않는다.

## 신규성 검사와 봉인

과거 `research_design` 16 query와 `maps/`, `scenarios/`, `results/raw/`,
`results/analysis/` 아래 모든 map YAML·scenario YAML을 읽어 정정판 v2 grid/query
identity(`results/turn_aware_query_identity_v2.py`)로 비교한다. 새 6지도는 서로와 과거
지도에 exact 중복이 없어야 하고, 12 query도 서로·과거와 중복이 없어야 한다. 초기·목표
footprint가 충돌하면 거부한다. 각 scenario는 저장 뒤 `validate_scenario_roundtrip`으로
지도·좌표·identity를 재확인한 다음 봉인한다.

runner는 planner 실행 전에 `protocol.json`과 `seal.json`을 쓴다. source hash는 `src`
전체, 후보 plugin, runner, identity 도구를, input hash는 지도·query·형상·신규성·설계
snapshot을 포함한다. 각 query 전후에 봉인을 확인하고 실행 시작 marker를 exclusive로
만들어 중단·완료한 폴더는 재실행하지 않는다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/smoothing_holdout.py --output-dir results/raw/smoothing_holdout_20261123
```

## 사전 고정한 판정과 보고 항목

- 주 지표는 A* 기준 같은 map/query/seed 36쌍의 reach win/loss와 도달률 차이다.
- **판정 규칙**: 전체 win > loss이고 세 family 모두 net loss가 없으면 "held-out 지지",
  아니면 "지지하지 않음"으로 기록한다. 표본이 작아 통계적 유의성은 주장하지 않는다.
- 보조 지표: Hybrid A*와의 같은 쌍 도달 비교, 양쪽 도달 조건부 RMSE·완료시간 delta,
  양쪽 주행 조건부 clearance delta(각 조건의 쌍 수 포함), family·query별 도달수,
  후처리 채택률, seed 중복 없는 계획시간 median/P95.
- ablation이 A*와 같은지(평활화만으로는 차이가 없는지)를 함께 보고한다.
- worst case는 모든 실패, planner별 성공 RMSE 상위3과 주행 clearance 하위3이다.
- 각 query의 요약·경로·전체 궤적 CSV, manifest, analyze, PNG를 저장하고 완료 후 모든
  산출물 hash를 기록한다. 실패행과 종료 원인을 삭제하지 않는다.

구현·테스트를 모두 작성할 때까지 테스트·실험 0회를 유지한 뒤 관련+전체 pytest와 봉인
실행을 한 묶음으로 수행한다. 테스트는 held-out 지도에서 planner를 실행하지 않는다.
결과는 실행 후 아래에 덧붙인다.
