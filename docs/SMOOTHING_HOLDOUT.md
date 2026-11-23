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

## 봉인 후 단일 실행 결과

구현·테스트 작성 뒤 관련 pytest **5 passed (1.58s)**, 전체 **130 passed (10.68s)**와
봉인 실행을 한 묶음으로 수행했다. 실행은 한 번이며 결과를 본 뒤 후보·파라미터 변경,
재실행, 추가 실험은 0회다. 신규성 검사는 과거 map 항목27개(고유19)와 query 항목31개
(고유31)를 v2 identity로 대조했고 새 6지도·12 query의 exact 중복은 0이다. source46개와
input32개를 각 query 전후에 확인했다.

```text
protocol SHA-256: 936d73a9e38751fc6c6cfef5e6a076ec8fddb1310eb8fde2e7ccbd9ebb29950f
design snapshot: 099c382fdc1c9a3237672e2ba0b4ccb9908ff72a64e9dfa114b8cf8bf0eea684
```

180행 모두 계획 성공이며 timeout·계획 실패는 0이다. 분모는 planner당 36 episode다.

| planner | 도달/36 | 충돌 | 후처리 채택 query/12 | 성공 RMSE 중앙값(m) | 성공 시간 중앙값(s) | 계획 시간 median/P95(ms) |
|---|---:|---:|---:|---:|---:|---:|
| Dijkstra | 0 | 36 | – | n/a | n/a | 10.4 / 17.3 |
| A* | 3 | 33 | – | 0.1123 | 10.85 | 5.2 / 13.4 |
| Hybrid A* | 15 | 21 | – | 0.0422 | 11.65 | 176.2 / 487.8 |
| **후보(목표0.30)** | **18** | **18** | 6 | 0.0359 | 10.98 | 93.1 / 157.3 |
| ablation(목표0) | 3 | 33 | 1 | 0.0367 | 10.80 | 94.7 / 192.5 |

**판정: held-out 지지.** 후보는 A* 대비 36쌍에서 승리15·패배0(도달률 +0.417)이고
family별 net은 staggered_windows +6, offset_islands +3, slalom_walls +6으로 net loss가
없다. 양쪽 도달은 3쌍뿐이며 RMSE delta 중앙값 −0.0725m, 완료시간 delta −0.05s다.
양쪽 주행 36쌍의 최소 clearance delta 중앙값은 0m(충돌 pose의 0 포함)다. ablation은
A* 대비 승패 0으로, 이득은 평활화가 아니라 clearance 반발항에서 나온다.

Hybrid A*와 같은 query·seed 36쌍을 비교하면 후보만 도달9, Hybrid만 도달6, 둘 다 도달9다.
Hybrid A*보다 우월하다는 판정 규칙은 사전에 두지 않았으므로 기술통계로만 보고한다.

| family/지도/query | A* | Hybrid A* | 후보 | 후보 후처리 |
|---|---:|---:|---:|---|
| staggered_windows/a/q0 | 0 | 3 | 3 | 채택 |
| staggered_windows/a/q1 | 0 | 0 | 3 | 채택 |
| staggered_windows/b/q0 | 0 | 3 | 0 | 곡률 거부 1.587/m |
| staggered_windows/b/q1 | 3 | 3 | 3 | 채택 |
| offset_islands/a/q0 | 0 | 0 | 0 | 곡률 거부 1.837/m |
| offset_islands/a/q1 | 0 | 3 | 3 | 채택 |
| offset_islands/b/q0 | 0 | 0 | 0 | footprint 거부 |
| offset_islands/b/q1 | 0 | 3 | 0 | 곡률 거부 1.646/m |
| slalom_walls/a/q0 | 0 | 0 | 0 | 곡률 거부 1.502/m |
| slalom_walls/a/q1 | 0 | 0 | 3 | 채택 |
| slalom_walls/b/q0 | 0 | 0 | 3 | 채택 |
| slalom_walls/b/q1 | 0 | 0 | 0 | 곡률 거부 1.585/m |

모든 칸의 분모는 3 seed다. 후처리를 채택한 6 query는 18/18 도달했고, 거부한 6 query는
A* 경로로 되돌아가 A*와 같이 모두 충돌했다. 거부 6건 중 5건이 곡률 한계(1.4685/m)
초과였다. 결정적 재계획 감사의 경로 길이는 저장된 24개 계획과 모두 일치했다. 전체
wall time은 17.6s다(분석·I/O·봉인 검증 포함, 속도 benchmark 아님).

## 산출물과 판단

원본은 ignore된 `results/raw/smoothing_holdout_20261123/`이며 `complete.json`이 산출물
164개 hash를 기록한다. 공유용 protocol/seal/설계 snapshot/신규성/집계/paired/worst/채택
감사와 지도·query 사본은 `results/analysis/smoothing_holdout_20261123/`, 대표 PNG 4장은
`results/figures/smoothing_holdout_20261123/`에 있다. 네 장 모두 시각 검토했다.

후보는 사전 규칙을 통과했다. 다만 이득은 "후처리가 채택되면 도달"이라는 형태로 나타나며
채택률이 6/12에 그친다. 남은 실패의 주원인은 곡률 한계 초과 거부이므로, 기본 planner로
승격하기보다 곡률 제약을 직접 다루는 후속 개선(예: 거부 시 시작 구간 처리나 곡률
투영)을 별도 개발 후보로 정의하는 것이 다음 단계다. 이 evaluation은 이미 노출됐으므로
그 후속 후보의 미사용 평가로 다시 쓰지 않는다. 한계: 지도 6개·query 12개·seed 3개,
0.2m 격자, 고정 tracker, 양쪽 도달 쌍 3개뿐인 조건부 지표다.
