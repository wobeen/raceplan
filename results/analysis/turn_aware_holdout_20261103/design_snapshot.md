# 방향-state 후보 신규 split 사전 프로토콜 — 2026-11-03

## 질문과 고정 후보

demo에서 관측한 방향변화 비용의 추종 오차/주행시간/여유 trade-off가 새로운 지도와
query에서도 나타나는지 확인한다. `TurnAwareAStar`의 가중치0.20m/rad, 가중치0
ablation, 기존 Dijkstra/A*/Hybrid A*를 그대로 사용한다. validation 결과로 후보나
가중치를 선택하지 않고 evaluation도 같은 후보로 한 번 실행한다. 후보 구현 설명은
[TURN_AWARE_CANDIDATE.md](TURN_AWARE_CANDIDATE.md)를 기준으로 한다.

## 실행 전 고정한 split과 예산

최소 규모는 **2family×2split×지도당2query×3seed×5planner=120episode**다.
split당2지도·4query·60episode로, family별 성공/실패와 같은 query/seed의 paired
차이를 볼 수 있다. 지도2개로 일반화의 통계적 유의성이나 폭넓은 효과는 입증할 수 없다.

신규 지도는10.4×7.2m, 해상도0.2m이며0.2m 외벽을 둔다. 기존 연구8×6m,
demo12×8m, 통로폭8×4.1m 지도와 크기가 다르고 내부 형상도 새로 정의했다.
`results/turn_aware_holdout.py`의 design 함수가 결과 확인 전에 아래 형상을 고정한다.

| family | validation 내부 장애물(m) | evaluation 내부 장애물(m) |
|---|---|---|
| staggered_windows | x3.0–3.6 벽의 y2.0–4.0창, x6.6–7.2 벽의 y3.6–5.8창 | x2.6–3.2 벽의 y3.0–5.0창, x6.2–6.8 벽의 y1.4–3.6창 |
| offset_islands | 사각형(3.0,1.4)–(4.6,3.4), (5.8,3.8)–(7.4,5.8) | 사각형(2.8,3.6)–(4.8,5.8), (6.0,1.2)–(7.8,3.2) |

각 family의 validation query는(1.1,1.5)→(9.3,5.7), (1.1,5.7)→(9.3,1.5),
evaluation은(1.3,1.7)→(9.1,5.5), (1.3,5.5)→(9.1,1.7)이다. 모든 yaw는0rad다.
Validation seed11/12/13, evaluation21/22/23으로 분리한다. 잡음은 위치0.02m,
초기yaw0.02rad, steering0.01rad, speed measurement0.02m/s이고 초기속도 잡음0이다.

계획은 query/planner당1회, 총40회이며 timeout2s, simulation30s/dt0.05s이다.
계획 cooperative 예산 합계는80s, 최대 simulated 주행량은3600s/72000step이다.
계획시간은4query/split의 자체 보고값4개만 집계하며 seed별 중복을 제거한다.
예열이나 결과를 본 재계획을 하지 않는다. timeout은 hard wall deadline이 아니다.
별도로 전체/각split wall time도 기록하며 분석·I/O·seal 검증 비용을 포함한다.

모든 planner는 같은 지도·query·차량·tracker·seed·잡음을 사용한다. inflation0으로
원본 물리 지도를 planning/simulation에 공통 사용하고 guard/recovery는 기존 CLI대로
비활성이다. 점-grid와 Hybrid 회전 사각형 탐색 표현의 차이는 유지하며 동일한 차량
충돌 제약을 쓰는 알고리즘끼리의 효과로 해석하지 않는다. 성공은 충돌 없이0.5m
이내 진입, yaw는 참고값이다. 해상도0.2m의 결과를 이전0.1m 연구와 합치지 않는다.

## 신규성 검사와 봉인

과거 `research_design`의 validation/evaluation16query를 생성하고 maps/scenarios 및
기존 results/raw의 map YAML 전체를 읽어 grid shape/resolution/origin/occupied의
canonical fingerprint를 비교한다. 신규4지도 서로와 과거 지도에 exact 중복이 없고,
grid+start+goal query fingerprint도 중복이 없어야 한다. 초기/목표 footprint도 검사한다.
이는 파일명 변경으로 과거 지도를 재사용하는 것을 막는 검사다. 같은 구조적 family의
다른 형상이므로 새로운 family 일반화로 부르지 않는다.

runner는 양split의 지도·query를 먼저 생성한 다음 어떤 planner도 실행하기 전에
`protocol.json`과 `seal.json`을 저장한다. source hash는 src 전체/후보/runner,
input hash는 지도image/YAML/query/형상JSON/신규성 검사/설계 snapshot을 포함한다.
각query 실행 전후와 split 사이에 hash를 확인한다. 실행시작 marker를 exclusive로
생성하므로 중단·완료한 같은 폴더는 재실행/재개하지 않는다. 기존 폴더도 덮어쓰지 않는다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/turn_aware_holdout.py --output-dir results/raw/turn_aware_holdout_20261103
# 별도 봉인 확인이 필요하면 --prepare-only 후 동일 경로에 --execute-sealed 사용
```

한 명령은 prepare→seal→validation1회→evaluation1회 순서다. 검증 결과를 읽고
설정/코드를 바꾸는 분기가 없다. 결과 노출 후에는 이 evaluation을 차기 후보의
미사용 평가로 다시 사용하지 않는다.

## 사전 고정한 보고 항목

- split/planner/family별 도달·충돌·timeout·계획실패를 전체 episode 분모로 저장한다.
- paired 기준은 A*, 같은map/query/seed다. reach win/loss와 성공률 차이를 모든pair에서
  계산한다. RMSE/완료시간 delta는 양쪽도달 조건부, clearance delta는 양쪽주행 조건부다.
  각조건을 만족하는 pair 수를 함께 저장한다. 표본이 작아 통계적 유의성을 주장하지 않는다.
- worst cases는 모든실패, split/planner별 성공RMSE 상위3개와 실제clearance 하위3개를
  고정 규칙으로 보존한다. 같은episode가 여러기준에 나타날 수 있다.
- 계산비용은 seed중복 없는 planning4회/split/planner의 median/P95·expanded nodes 및
  전체wall time을 보고한다. 4회값P95는 기술통계이며 안정적인 tail 추정이 아니다.
- 각query에 요약/경로/전체궤적CSV, manifest, analyze와 PNG를 저장하고 완료 후 전체
  산출물hash를 기록한다. 실패행과 종료원인을 삭제하지 않는다.

구현/테스트 작성이 모두 끝날 때까지 테스트/실험0회를 유지한 뒤 관련+전체pytest와
신규validation/evaluation을 묶어 실행한다. 신규split의 planner 결과를 테스트에서
사전 계산하지 않는다. 결과와 Astra독립검증은 실행 후 문서에 덧붙인다.
