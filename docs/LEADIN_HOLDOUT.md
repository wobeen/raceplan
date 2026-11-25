# `leadin_rescue_k3` held-out 평가 — 사전 등록 (2026-11-25, 정책 v2)

## 착수와 질문

사용자 지시(2026-11-25): "추천대로 leadin_rescue_k3 held-out 평가 진행해". 이 평가는
[여유 상향 개발 비교](MARGIN_RESCUE_DEVELOPMENT.md)의 사후 관찰을 확인한다. 그 비교에서 선택할 수
없는 ablation이던 `leadin_rescue_k3`가 새 절차 생성 개발 입력 24 query에서 기준
`smoothed_low_clearance` 대비 +3 query, 손실 0을 보였다.

질문: 같은 생성기의 **예약된 seed(2000 이상)**에서도 `leadin_rescue_k3`가 기준 후처리가 거부한
query를 기준보다 더 많이 도달시키는가.

이것은 정책 v2의 첫 held-out이다. 후보 코드는 `examples/leadin_rescue_planner.py`의 `LeadInRescueK3`
그대로이며(사전 등록 `6f8456a` 이후 변경 없음), 이 평가 결과로 수정하지 않는다.

## 입력: 절차 생성과 층화 선택

- **생성기**: 개발 생성기(`results/margin_rescue_development.py`의 `interior`, 끝점 footprint 여유
  0.15m, query 범위)를 그대로 쓴다. family는 seed 순서대로 돈다. 생성 범위만 예약 seed로 바꾸며,
  구현은 `results/leadin_holdout.py`의 `generate`다. 개발 seed 1000–1011과 두 smoke seed
  (1999, 1997/1998)는 쓰지 않는다.
- **풀**: seed 2000–2999를 순서대로 훑어 family마다 신규 지도 20개씩, 총 60지도·최대 120 query를
  모은다. 신규 지도는 커밋된 지도·시나리오, 개발·smoke 생성 지도, 이미 풀에 든 지도와 exact 중복이
  아니고 점유 셀 IoU가 0.9 미만인 것이다. 중복이면 건너뛰고 기록하며 다시 뽑지 않는다. 사전 등록
  테스트(계획·주행 없음)에서는 seed 2000–2107로 풀이 채워졌다. 끝점 여유를 만족하는 query를 50회
  안에 못 뽑은 query는 `unavailable`로 기록한다.
- **층화(계획만, 주행 없음)**: 풀의 모든 query를 기준 후처리로 **계획만** 해서 채택·거부를 분류한다.
  그다음 풀 순서대로 **거부 16개와 채택 8개**를 고른다. 거부 query는 후보 결과가 기준과 달라질 수
  있는 곳이고, 채택 query에서는 후보가 기준 경로를 그대로 반환해야 한다(불변식 검사). 분류는 후보를
  주행하지 않으며, 선택 규칙은 코드에 고정되어 있다.
- 주행 seed는 지금까지 쓰지 않은 **41/42/43**이다. 잡음은 이전과 같고 timeout은 2s다.
- planner는 A*, Hybrid A*, 기준, 후보이며 24 query × 3 × 4 = 288 episode다.

## 판정 규칙 (runner의 `decide`)

- **분석 단위**: query. seed 2/3 이상 도달하면 도달로 본다.
- **감사**: 기준과 후보를 결정적으로 재계획해 저장 경로와 pose 단위로 비교한다. 다음 중 하나라도
  해당하면 `invalid_audit`이다: 경로 불일치, 채택 query에서 후보 경로와 기준 경로가 다름, 감사의
  기준 채택·거부 라벨이 층화 분류 라벨과 다름. 한쪽만 구제 시간 초과가 나도 경로 불일치로 무효가
  된다. 양쪽 모두 시간 초과면 경로가 같아 유효이고, 구제 실패로 센다(`rescue_timeouts`에 기록).
- **판단 불가**: 선택된 거부 query가 8개 미만이면 판단 불가다.
- **held-out 지지**: 후보가 기준이나 A*가 도달한 query를 하나도 잃지 않고, 기준 대비 query 순증이
  max(2, ⌈0.25 × 거부 query 수⌉) 이상이어야 한다. 거부 16개면 4개다. 그 외는 `not_supported`다.
- **선택 순서(판정 순서)**: 감사 → 판단 불가 → 손실 → 순증.
- **무회귀 근거**: "거부 ∧ 기준 fallback(A* 경로) 도달" query가 2개 이상이면 `tested`, 아니면
  `untestable`로 보고한다. 채택 query에서는 후보 경로가 기준과 같으므로 구조상 손실이 나올 수 없고,
  거부 query의 fallback 도달은 개발에서 0/9였다. 그래서 "손실 0"은 거의 자동으로 충족되고, 판정은
  사실상 "순증 ≥ 4/16" 하나다. 이 점은 정책 템플릿("층 최소치 미달 → 판단 불가")에서 벗어난다.
  `untestable`인 채로 지지가 나오면 결과에 **"순증만 지지, 무회귀 미검정"**(`verdict_label`)을 붙이고
  그렇게 해석한다. A* 대비 손실은 층별(`losses_vs_astar_by_stratum`)로 나눠 보고한다. 채택 층의 손실은
  후보와 무관한 기준 평활화 자체의 손실이지만, 사전 규칙대로 불지지로 처리한다.
- **판정별 후속**:
  - 지지: 기록만 한다. **승격 체크리스트를 모두 충족하지 못하면 이 평가는 승격용 held-out 횟수에
    넣지 않는다**(`counts_toward_promotion`).
  - 불지지: 음성 held-out으로 기록하고 연구 보관을 유지한다.
  - 판단 불가·감사 무효·중단: 기록만 하고 재실행하지 않는다.
- **승격 체크리스트**는 판정과 별개로 보고만 한다. 항목은 다음과 같다.
  - 24 query
  - A* 성공 query 30%
  - A* 성공 query 무손실
  - 도달률 순증 +25%p(기준 대비와 A* 대비 둘 다)
  - Hybrid query net ≥ 0
  - 후처리 채택 75%
  - 계획시간 P95 ≤ 0.5s

  층화 선택 때문에 A* 성공 비율과 채택 비율은 이 설계에서 충족되기 어렵다. 따라서 이 평가는 승격 판정이
  아니라 개발 관찰의 확인이다.

## 사전 예측과 제한

- 개발 입력에서 후보의 구제 경로는 거부 9개 중 4개였고 그중 3개가 도달했다. 계획시간 P95는 1.34s였다.
  같은 비율이면 거부 16개에서 약 5개 순증이 기대되지만, 표본이 작아 4개 기준을 넘을지는 불확실하다.
- 생성기는 노출된 지도 설계 범위를 흩뜨린 것이라 같은 family의 일반화만 본다.
- 층화 선택은 기준 후처리의 계획 결과를 쓴다. 후보와 기준이 같은 A* 경로에서 출발하므로, 선택이
  후보의 성패와 독립이라고 보장할 수는 없다.

## 실행

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/leadin_holdout.py `
  --output-dir results/raw/leadin_holdout_20261125 --prereg-commit <사전 등록 커밋>
```

- runner는 추적 파일이 dirty이거나 사전 등록 커밋이 HEAD의 조상이 아니면 거부한다.
- 계획 전에 `novelty.json`을 쓴다. 여기에는 실제로 훑은 seed 범위와 건너뛴 중복이 들어간다. 분류 후
  `classification.csv`와 `protocol_start.json`을 쓴다.
- 분류, 입력 기록, 계획, 감사, 집계 중 어느 단계에서든 예외가 나면 `aborted.json`을 남긴다.
  `decision.json`이 없으면 중단으로 보고 재실행이나 재판정을 하지 않는다.
- 다른 무거운 작업이 없을 때 실행한다. 구제 시간 초과는 벽시계에 의존한다.
- 생성 입력은 커밋하지 않는다(생성기로 재현된다).
- **seed 소진**: 실제로 훑은 범위(2000부터 마지막 스캔 seed까지)는 전부 소진된 것으로 본다. 여기에는
  미선택 query의 기준 채택·거부 라벨이 `classification.csv`에 노출된 지도도 포함된다. 다음 held-out은
  그 뒤 seed부터 쓴다.

## 독립 검토

1차: `anthropic/claude-fable-5-2`가 `14bb026`을 검토했고 판정은 **"실행 가능"**(P1 없음)이었다.
P2는 실행 전에 반영했다.

- **P2-1**: `untestable` 지지의 해석과 템플릿 이탈을 위에 적고 `verdict_label`을 추가했다.
- **P2-2**: 체크리스트를 충족하지 못하면 승격 횟수에 넣지 않는다고 적고 `counts_toward_promotion`을
  추가했다.
- **P2-3**: 중단 기록 범위를 분류 단계부터로 넓혔다(코드).
- **P2-4**: 유휴 실행과 양쪽 timeout 처리를 위에 적었다.
- **P2-5**: 실제 스캔 범위를 기록하고(코드), 그 범위 전체를 소진으로 선언했다.
- **P2-6**: 감사 라벨과 층화 라벨이 다르면 `invalid_audit`으로 처리한다(코드).
- **P3**:
  - A* 대비 순증을 승격 체크리스트에 추가했다.
  - A* 손실을 층별로 보고한다.
  - 선택 순서를 명시했다.
  - 테스트 docstring을 고치고, smoke 판정을 `undecidable`로 고정했다.
  - 라벨 교차검증, `tested`, A*만 손실 분기를 테스트에 추가했다.
  - 그대로 둔 것: family 오프셋 차이(분포 동일), `unavailable` 지도의 정원 차지, 생성기 복제 코드,
    `seal.json` 미작성(protocol·hash 기록과 사전 등록 커밋으로 대신), 출력 폴더 기준 input hash.

2차 반영 코드는 재검토를 받지 않았다. 이 반영을 커밋한 것이 최종 사전 등록이다.

## 단일 실행 결과 (2026-11-25)

최종 사전 등록 `55d48b8`에서 추적 파일 diff 0과 `tests/test_leadin_holdout.py` **7 passed**를 확인했다.
이어서 runner를 한 번 실행했다(실행 커밋 동일, wall time 45.5s, 288 episode).

- 풀은 seed 2000–2107을 훑어 신규 지도 60개를 채웠다. 근사·exact 중복으로 22개 seed를 건너뛰었으며, 이
  범위 전체가 소진됐다.
- 기준 후처리의 계획 분류는 채택 85, 거부 34, unavailable 1 query였다. 그중 거부 16개(seed 2001–2046)와
  채택 8개(seed 2000–2004)를 골랐다.
- 감사: 재계획 경로 48개가 모두 일치했다. 채택 query의 경로 동일, 층화 라벨 일치를 확인했고 구제
  timeout은 0건이었다.

**판정: 불지지(`not_supported`).** 후보는 기준 대비 순증 **+2**로, 필요 순증 4에 못 미쳤다. 손실은
기준 대비와 A* 대비 모두 0이었다. 무회귀 근거는 `untestable`이다(거부 ∧ fallback 도달 0개).

| planner | 도달 query/24 | 도달 episode/72 | 계획시간 median/P95(ms) |
|---|---:|---:|---:|
| A* | 2 | 6 | 3.5 / 7.2 |
| Hybrid A* | 7 | 21 | 153.1 / 382.6 |
| 기준 `smoothed_low_clearance` | 7 | 21 | 79.4 / 125.4 |
| 후보 `leadin_rescue_k3` | 9 | 27 | 356.9 / 501.6 |

기전은 다음과 같다.

- 후보는 거부 16개 중 5개에서 검증을 통과한 구제 경로를 만들었다. 그중 2개만 도달했다
  (seed2009 staggered_windows q0, seed2016 offset_islands q0).
- 도달한 두 경로의 footprint 여유는 0.081m와 0.020m였다.
- 충돌한 세 경로(seed2006 staggered_windows q1, seed2016 offset_islands q1, seed2031 offset_islands
  q0)의 여유는 0.030–0.050m였다. 추종 RMSE는 0.030–0.051m, 최대 추종 오차는 0.043–0.086m였고, 출발
  1.5–2.9s에 첫 장애물 모서리에서 충돌했다.
- 구제하지 못한 11개는 곡률 거부 8, footprint 거부 3이었다.
- 개발 비교의 구제 후 도달 3/4가 이번에는 2/5였다. 경로 여유가 도달을 가르지 않는다는 점은 개발 비교와
  같았다(0.020m로도 도달했다).

보조 지표(판정과 무관):

- Hybrid A* 대비 query net은 +2다(후보 9, Hybrid 7). 거부 층에서 Hybrid만 도달한 query가 3개 있다.
- 승격 체크리스트에서 충족한 항목은 24 query, A* 성공 query 무손실, A* 대비 순증 +25%p(+7/24), Hybrid
  net ≥ 0이다.
- 미충족 항목은 A* 성공 비율 30%(2/24), 기준 대비 순증 +25%p(+2/24), 후처리 채택 75%, 계획시간 P95
  ≤ 0.5s(501.6ms)다. 따라서 `counts_toward_promotion`은 False다.

**해석**: 개발 입력에서 본 +3 query는 예약 seed에서 사전 기준(+4/16)을 넘지 못했다. 후보는 기존 후처리가
거부한 query 일부를 손실 없이 되살리지만 그 규모가 작다(16개 중 2개). 구제 경로의 대부분은 출발 직후 첫
모서리를 지나다 충돌한다. 사전 규칙대로 `leadin_rescue_k3`는 연구 보관을 유지하며, 이 입력과 소진된
seed 범위로 추가 조정하지 않는다.

산출물:

- 원본: `results/raw/leadin_holdout_20261125/`(ignore, 생성 입력 포함)
- 공유본: `results/analysis/leadin_holdout_20261125/`(novelty, classification, protocol_start, protocol,
  decision, summary, queries, acceptance)
- 대표 PNG 2장: `results/figures/leadin_holdout_20261125/`(도달 seed2009, 구제 후 충돌 seed2006)
