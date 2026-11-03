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
위 명령은 보존된 v1 실행 기록이다. v1의 query identity 숫자형 직렬화에 대한
사후 정정과 차기 봉인용 v2 identity 검증은 아래 Astra P2 정정 절을 적용한다.

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

## 봉인 후 단일 실행 결과

구현/테스트 작성을 끝낸 뒤 관련pytest1회 **12 passed (1.53s)**, 전체1회
**88 passed (2.95s)**, validation→evaluation을 한 묶음으로 실행했다. evaluation은
단 한 번 실행했고 결과를 본 후보 변경·가중치 재선택·추가실험은0회다.
새4지도/8query의 과거 exact 중복은0이다. 신규성 검사의 map fingerprint52항목은
source에서 생성한16항목과 저장 map YAML36항목의 합계이며 중복을 포함한다.
과거 source16query와 기존 지도 입력hash72개도 대조했다. 실행 전 봉인은 다음과 같다.

```text
protocol SHA-256: bbf5e116e779403ce8ef662f5f5c69f9e06d9eb841816ca15b9e7aa6647c7e3f
design snapshot: ee0473271c10efb568de4941d8f2f112405e3813749280ad9a55159258284d25
```

source41개와 input22개를 각query전후에 확인했다. 모든120행은 계획성공이고,
전체 도달29·충돌91·timeout0·계획실패0이다. split별 결과는 다음과 같다.

| planner | validation 도달/12 | validation 충돌 | evaluation 도달/12 | evaluation 충돌 |
|---|---:|---:|---:|---:|
| Dijkstra | 0 | 12 | 0 | 12 |
| A* | 6 | 6 | 0 | 12 |
| Hybrid A* | 8 | 4 | 6 | 6 |
| 방향-state A* 0.20 | 0 | 12 | 3 | 9 |
| 방향-state 가중치0 | 6 | 6 | 0 | 12 |

후보의 validation12쌍은 A*대비6패·0승(-0.50), evaluation은3승·0패(+0.25)다.
evaluation 승리3개는 모두 `offset_islands/q0`의 seed21/22/23에 한정된다.
후보와 A*가 동시에 도달한pair는 양split모두0이므로 **paired RMSE/주행시간 delta를
계산할 수 없다**. 실패를 빼고 후보 성공RMSE0.03013m를 A*와 비교하지 않는다.
모두 주행한12쌍의 최소clearance delta 중앙값은 validation-0.00752m,
evaluation0m이다. 충돌pose의clearance0과 짧은 실패 주행이 포함되는 기술통계다.
가중치0은 두split모두 A*대비reach win/loss0이고 계산 가능한paired 지표delta0이다.

query별 도달수는 아래와 같다. 모든칸은3seed분모이며 나머지는 충돌이다.

| split/family/query | A* | 후보0.20 | Hybrid A* |
|---|---:|---:|---:|
| validation/staggered_windows/q0 | 3 | 0 | 3 |
| validation/staggered_windows/q1 | 0 | 0 | 0 |
| validation/offset_islands/q0 | 0 | 0 | 2 |
| validation/offset_islands/q1 | 3 | 0 | 3 |
| evaluation/staggered_windows/q0 | 0 | 0 | 0 |
| evaluation/staggered_windows/q1 | 0 | 0 | 3 |
| evaluation/offset_islands/q0 | 0 | 3 | 3 |
| evaluation/offset_islands/q1 | 0 | 0 | 0 |

## Worst cases와 계산비용

사전 규칙으로 모든실패 및split/planner별 성공RMSE상위3·clearance하위3을
`{split}_worst.csv`에 저장했다. 후보의 validation `staggered_windows/q0/seed11`은
RMSE0.02935m여도8.70s, 목표거리3.00044m에서 충돌했다. 계획의 내부회전합은
A*18.84956→후보1.57080rad였지만 회전합 감소가 차량 여유를 보장하지 않았다.
evaluation `staggered_windows/q1` 후보는 세seed모두1.65s에 충돌했고 목표가
7.712–7.750m 남았다. evaluation성공은 `offset_islands/q0`에서만 나왔으며,
가장큰 성공RMSE는seed23의0.03294m, 해당실제clearance0.11967m였다. 세성공의
최저clearance는seed21의0.11713m다. 정지/짧은충돌을 성공으로 세지 않았다.

planning은4query값/split/planner이며 seed중복을 제거했다.

| planner | validation median/P95(ms) | evaluation median/P95(ms) | evaluation expanded nodes median |
|---|---:|---:|---:|
| Dijkstra | 8.825 / 9.284 | 11.662 / 13.442 | 1390 |
| A* | 2.901 / 3.029 | 3.359 / 4.070 | 398.5 |
| Hybrid A* | 95.833 / 135.290 | 119.699 / 131.430 | 540 |
| 후보0.20 | 17.517 / 20.249 | 18.051 / 22.171 | 1244.5 |
| 가중치0 | 19.887 / 29.136 | 19.816 / 22.547 | 1804.5 |

실행/분석/I/O/검증을 포함한wall time은 validation3.041s, evaluation2.708s,
총5.758s였다. 계획반복이4개뿐이고 GUI등외부부하를 통제하지 않아 성능benchmark의
속도추정으로 일반화하지 않는다. 어떤 planner도2s예산을 소진하지 않았다.

## 산출물과 판단

원본은 `results/raw/turn_aware_holdout_20261103/`이며 `complete.json`이 완료 상태와
산출물120개 hash를 저장한다. 각 query의 전체 경로/궤적, 계획 실패 포함15행,
manifest/analyze/PNG를 보존했다. 공유용 protocol/seal/설계/신규성/집계/paired/worst와
지도/query 사본은 `results/analysis/turn_aware_holdout_20261103/`, PNG8장 복사본은
`results/figures/turn_aware_holdout_20261103/`에 있다. 공유본의complete.json은 원본
raw-tree의 hash 목록이다. 원본을 이동하지 않았고 대표적인 validation 회귀와 evaluation
성공 PNG2장을 시각검토했다. raw는 ignore된 로컬 자료이므로 Git만으로 전체 궤적이 복원되지 않는다.

신규 split에서 방향 비용 후보는 validation에 실패했고 evaluation의 일부 query만 복구했다.
일반적인 안전성/도달률 개선 증거는 부족하며 기본 planner나 회복 정책으로 승격하지 않는다.
점경로와 차량 footprint 차이, 0.2m 격자, 고정 tracker의 코너 추종, 작은 지도2개/split,
동일 family 내 형상 holdout이라는 한계가 있다. 계획 성공과 실제 주행 성공의 차이를 보여주는
음성 결과로 보존한다. 추가 후보 설계가 필요하면 본 evaluation은 이미 노출됐으므로 차기
최종 평가에 새 split을 준비해야 한다.

## Astra P2 정정: 숫자형 query identity

Astra가 v1 `query_fingerprint`의 숫자 직렬화 결함을 발견했다. 설계의 yaw는 정수0,
`load_scenario`로 읽은 yaw는 실수0.0이라 좌표값이 같아도 JSON 바이트가 달라진다.
8개 member의 저장 query fingerprint는 설계 객체를 재현하지만 저장 scenario를
재로딩한 query identity와 일치하지 않는다. 지도 fingerprint와 실제 봉인된 scenario
파일 bytes는 일치한다. 실행 manifest의 좌표도 같은 입력을 사용했는지 별도로 확인한다.

원시 protocol/seal/입력/결과/사전 설계 snapshot과 실행 소스인
`results/turn_aware_holdout.py`는 그대로 보존한다. 사후 정정을 원래의 사전 봉인으로
표현하지 않으며 기존 hash를 바꾸거나 evaluation을 다시 실행하지 않는다.

별도 `results/turn_aware_query_identity_v2.py`는 int/float 동등값과 signed zero를
정규화한 버전2 grid/query identity를 제공한다. 유한한 실수만 허용하고 좌표를 반올림하지
않는다. 정수는 그대로 보존해2**53보다 큰 정수도 float 변환으로 잘리지 않는다.
차기 runner는 scenario를 저장한 뒤 `validate_scenario_roundtrip`으로 지도·start·goal과
canonical identity를 확인하고, 그 결과를 사용해 계획 전에 봉인해야 한다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/turn_aware_query_identity_v2.py --run-dir results/raw/turn_aware_holdout_20261103 --output-dir results/analysis/turn_aware_holdout_20261103_correction_v2
```

이 도구는 원본 source/input/artifact hash를 읽기 전용으로 검증하고 별도 새 폴더에
member별 old stored/design/round-trip hash, v2 design/round-trip hash, 좌표 동등성과
실행 manifest 대조를 기록한다. 원본 run 내부에는 결과를 쓰지 않는다. 숫자형·signed
zero·큰 정수 구분 및 scenario round-trip의 지도/좌표 변경 거부 회귀를 작성한 뒤,
관련/전체 pytest와 읽기 전용 정정 감사를 한 묶음으로 실행한다. 새 planner/simulation
호출은0회다. 테스트와 감사 결과는 실행 완료 후 기록한다.

교정 구현 완료 후 관련pytest1회 **15 passed (1.34s)**, 전체1회
**91 passed (3.88s)**와 읽기 전용 감사1회를 묶어서 실행했다. 원본 source41개,
input22개, 산출물120개 hash는 모두 일치하고 v1 runner/protocol/seal도 원래hash를
유지했다. 8개 member 모두 v1 stored/design hash가 일치하지만 v1 round-trip은
8개 불일치였다. v2 canonical design/round-trip은8개 모두 일치하고, 지도와
좌표는 tolerance 없이 동등하며 실행 manifest도8건 모두 같은 query와 일치했다.
별도 기록은 `results/analysis/turn_aware_holdout_20261103_correction_v2/correction.json`
및 `correction_sha256.json`이다. v2 hash는 버전이 다른 새 identity이며 기존 protocol의
field를 대체하지 않는다. evaluation planner/simulation 재실행은0회다.

영향 범위는 v1의 의미상 query fingerprint 재연결이다. 봉인된 입력 bytes·지도·좌표와
120개 주행 결과는 바뀌지 않았고, 지도 자체가 과거와 서로 disjoint여서 query 신규성
결론도 유지된다. 사후 교정임을 기록하고 원래 봉인을 다시 작성하지 않았다.
## Astra 최종 검증

Astra는 계획·주행 없이 원본과 v2 교정을 독립 재계산했다. 저장 correction 전체와
독립 결과 및 correction/tool hash가 일치했다. v1 round-trip8/8 불일치는 v2에서
0/8로 해소됐고 canonical query8개가 모두 고유하며 실제 입력 좌표·실행 manifest와
일치했다. 원본 source41/input22/artifact120 봉인과 120건 결과도 유효해 최종 승인했다.
