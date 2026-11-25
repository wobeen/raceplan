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
- **감사**: 기준과 후보를 결정적으로 재계획해 저장 경로와 pose 단위로 비교한다. 불일치가 있거나,
  채택 query에서 후보 경로가 기준 경로와 다르면 `invalid_audit`이다.
- **판단 불가**: 선택된 거부 query가 8개 미만이면 판단 불가다.
- **held-out 지지**: 후보가 기준이나 A*가 도달한 query를 하나도 잃지 않고, 기준 대비 query 순증이
  max(2, ⌈0.25 × 거부 query 수⌉) 이상이어야 한다. 거부 16개면 4개다. 그 외는 `not_supported`다.
- **무회귀 근거**: "거부 ∧ 기준 fallback(A* 경로) 도달" query가 2개 이상이면 `tested`, 아니면
  `untestable`로 보고한다.
- **판정별 후속**:
  - 지지: 기록만 한다. 승격에는 독립 held-out 1회와 [승격 기준](FEATURE_SCOPE.md) 충족이 더 필요하다.
  - 불지지: 음성 held-out으로 기록하고 연구 보관을 유지한다.
  - 판단 불가·감사 무효·중단: 기록만 하고 재실행하지 않는다.
- **승격 체크리스트**는 판정과 별개로 보고만 한다. 항목은 24 query, A* 성공 query 30%, A* 성공 query
  무손실, 도달률 순증 +25%p, Hybrid query net ≥ 0, 후처리 채택 75%, 계획시간 P95 ≤ 0.5s다. 층화 선택
  때문에 A* 성공 비율과 채택 비율 항목은 이 평가 설계상 충족되기 어렵다. 이 평가는 승격 판정이 아니라
  개발 관찰의 확인이다.

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

runner는 추적 파일이 dirty이거나 사전 등록 커밋이 HEAD의 조상이 아니면 거부한다. 계획 전에
`novelty.json`을, 분류 후 `classification.csv`와 `protocol_start.json`을 쓴다. 예외가 나면
`aborted.json`을 남기고 재실행하지 않는다. 생성 입력은 커밋하지 않는다(생성기로 재현된다).

## 독립 검토

사전 등록 커밋 뒤 실행 전에 읽기 전용 독립 검토를 받고 여기에 기록한다.
