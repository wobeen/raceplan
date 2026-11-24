# 출발 lead-in 구제 후보 개발 비교 — 사전 등록 (2026-11-24, 정책 v2)

## 착수와 범위

사용자 지시(2026-11-24): "새로 만든 정책은 우선 브랜치 하나 파서 개발 연구 시작해".
포괄적인 개발 연구 착수 지시이며, 주제(후처리 후보의 곡률 거부 해소)는 직전 held-out 문서의
다음 단계를 따라 총괄이 정했다. lead-in 구제라는 구체 주제에 대한 별도 승인은 받지 않았다.
브랜치 `research/policy-v2-curvature`에서 정책 v2([절차](COMMIT_PLAN.md),
[판정 템플릿](FEATURE_SCOPE.md), [봉인 기록](../results/README.md))의 첫 연구 스텝으로 진행한다.
이 스텝은 **개발 선택**이며 held-out 근거가 아니다. 선택된 후보가 있어도 새 held-out은
별도 사용자 승인 뒤에 진행한다.

## 문제, 사전 진단, 사전 노출

`SmoothedLowClearance`(목표 clearance 0.30m)는 후처리 경로가 곡률 한계(1.4685/m)나 footprint
여유를 넘으면 원래 A* 경로로 되돌아가고, 그 경우 대부분 충돌했다. 아래 20개 노출 query에서
기존 후보만 **계획(주행 없음)**해 거부 위치를 확인했다.

| 입력 묶음 | query | 기존 후보 채택 | 거부(사유) | 출처 |
|---|---:|---:|---|---|
| turn_aware validation | 4 | 4 | 0 | 커밋된 `smoothing_development_20261123/acceptance.csv` |
| turn_aware evaluation | 4 | 3 | 1 (곡률, staggered_windows q0) | 아래 계획 전용 실행에서 처음 관측, 커밋 자료 없음 |
| smoothing held-out | 12 | 6 | 6 (곡률 5, footprint 1) | 커밋된 `smoothing_holdout_20261123/acceptance.csv` |

곡률 거부 6건 중 5건의 최대 곡률이 출발 후 0–0.3m에 있었다. 시작 yaw 고정 구간과 바로 앞
장애물 때문에 출발 직후 급회전이 강제되는 것이 주원인이다.

**의도하지 않은 사전 노출(정책 위반 기록)**: 처음 구상한 "위반 구간 국소 강성 증가"(위반 지점
±0.5m의 2차 차분 가중치 ×4, 최대 3라운드)를 비개발 지도에서 점검하려 했다. 그런데 작업
커널의 변수가 개발 입력 목록으로 바뀌어 있어, 실제로는 같은 20 query에서 **계획만** 실행됐다.
결과는 곡률 거부 6건이 모두 footprint 거부로 바뀌어 구제 0건이었고, 원래 채택되던 1건을
잃었다. 이 구상은 폐기했고 코드와 실행 스크립트는 남아 있지 않다. 정책 v2가 금지한 것은
사전 등록 전 주행이지만, 계획 결과도 개발 입력의 정보이므로 위반으로 기록한다.

해석 제한:

- 후보 구상은 같은 20 query의 진단(출발 0–0.3m)에서 나왔고, 폐기한 첫 구상 다음의 두 번째
  구상이다. 결과는 표본 안의 선택이며 효과크기로 인용하지 않는다.
- turn_aware validation 4개는 이전 개발 비교와 seed·잡음이 같아 사실상 재현이다.
- 합성 설계 격자는 개발 지도와 크기(10.4×7.2m)·해상도(0.2m)·시작 배치를 공유한다.
- **새 후보(lead-in)는 20 query에서 계획·주행한 적이 없다.** 아래 합성 격자에서만 계획했다.

## 후보 설계 (합성 격자에서만)

설계와 파라미터는 `results/leadin_synthetic_check.py`의 합성 격자 54개에서만 정했다.
외벽이 있는 10.4×7.2m 지도에 시작 앞 수직 벽(x 1.6/2.0/2.4m, 아래 끝 y 1.6/2.0/2.4m부터 위
외벽까지), 시작 y 5.0/5.6/6.2m, 목표 (9.3, 1.1 또는 6.1)이다. 계획만 했고 주행은 없다.
재현 결과: 기존 후보는 54개 모두 거부(곡률 36, footprint 18)했다. `leadin_rescue_k3`와
`leadin_rescue_k6`는 각각 9개를 구제했고, 직선 ablation은 0개였다. 최대 계획시간은
k3 932.7ms, k6 1553.7ms, 직선 428.4ms다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/leadin_synthetic_check.py
```

## 후보 (`examples/leadin_rescue_planner.py`)

1. 기존 `SmoothedLowClearance`를 그대로 실행한다. 채택되면 **그 결과를 바꾸지 않고** 반환한다.
2. 거부된 경우에만 구제한다. 시작 자세에서 곡률 9개(±0.9×한계 균등, 0 포함)와 길이 3개
   (0.6/1.0/1.4m)의 등곡률 호를 만든다. 호 위 모든 표본에서 footprint 여유가 0.02m 이상인
   것만 남긴다.
3. 남은 호마다 호 끝에서 목표까지 A*를 계획한다. 호 끝 heading과 A* 진행 방향(0.5m 앞)의
   차이, 그다음 총 길이 순으로 정렬한다. A*는 호 끝이 속한 셀 중심에서 시작하므로 접합부가
   최대 0.141m 어긋난다. 이어 붙인 경로가 아래 검증을 통과해야만 반환하므로, 이 어긋남은
   구제율을 낮출 수는 있어도 검증되지 않은 경로를 내지는 않는다.
4. 상위 `attempts`개에 대해 호 점을 고정하고 나머지를 기존과 같은 방식(반발 0.30m,
   가중치 100, 100회)으로 평활화한다. 기존과 같은 검증(0.05m 간격 footprint 여유 0.02m,
   곡률 한계)을 통과한 첫 경로를 반환한다.
5. 모두 실패하거나 구제 중 계획 시간이 끝나면 기존 결과(A* 경로)를 반환한다
   (`rescue`=`failed`/`timeout`). 기존 후보 자체가 시간 초과·계획 실패면 그대로 반환한다.

| 이름 | 역할 | 설정 |
|---|---|---|
| `leadin_rescue_k3` | 후보 | 길이 0.6/1.0/1.4m, attempts 3 |
| `leadin_rescue_k6` | 후보 | 길이 0.6/1.0/1.4/1.8m, attempts 6 |
| `leadin_straight` | ablation, 선택 불가 | 곡률 0만, attempts 3 |

구조상 기존 후보가 채택한 query에서는 경로가 같으므로 차이가 날 수 없다. 차이는 기존 후보가
A* 경로로 되돌아간 query(위 표 기준 7개)에서만 생긴다. k6의 합성 최대 계획시간 1.55s는
timeout 2s에 가깝다. 구제 중 시간이 끝나면 결과가 벽시계에 따라 달라질 수 있으며, 그
경우 아래 감사 규칙에 따라 실행 전체가 무효가 된다.

## 데이터와 실행

- 입력: 이미 노출된 20 query. `turn_aware_holdout_20261103`의 validation·evaluation 8개와
  `smoothing_holdout_20261123`의 12개다(커밋된 `results/analysis/**/inputs` 사본).
- seed 11/12/13, 잡음은 이전 연구와 같다(위치 0.02m, 초기 yaw 0.02rad, steering 0.01rad,
  speed 0.02m/s). inflation 0, 계획 timeout은 시나리오 값 2s다.
- planner: A*, Hybrid A*, 기준 `smoothed_low_clearance`, 후보 2개, ablation. 총 360 episode.
- runner `results/leadin_rescue_development.py`는 추적 파일이 dirty이거나 사전 등록 커밋이
  HEAD의 조상이 아니면 실행을 거부한다. 계획 전에 `protocol_start.json`을 먼저 쓴다. 여기에
  실행 커밋, `uv.lock` hash, Python·OS, `raceplan` import 경로, 시나리오·지도 YAML·이미지의
  POSIX 경로 hash를 기록한다.
- 채택·구제 여부는 실행 뒤 결정적 재계획으로 얻고, 저장된 경로와 pose 단위로 완전히 같아야
  한다. 하나라도 다르면 판정은 `invalid_audit`이다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/leadin_rescue_development.py `
  --output-dir results/raw/leadin_rescue_development_20261124 --prereg-commit <사전 등록 커밋>
```

## 판정 규칙 (runner의 `decide`가 그대로 계산)

- **분석 단위**: query. 3 seed 중 2개 이상 도달하면 그 query를 도달로 본다.
- **효과 분모와 층**: 차이가 날 수 있는 곳은 기존 후보가 거부한 query뿐이므로, 그 집합이
  분모다. 4개 미만이면 "판단 불가"다.
- **무회귀**: 후보는 기존 후보 또는 A*가 도달한 query를 하나도 잃지 않아야 한다. 무회귀를
  실제로 검정할 수 있는 층은 "기존 후보가 거부 ∧ A* 경로로 되돌아가 도달"한 query다. 이 층이
  2개 미만이면 무회귀 근거는 `untestable`이다. 그때 선택에는 "순증만으로 선택, 회귀 검정
  불가" 표시를 붙인다. 위 표와 과거 결과(해당 query의 A* 경로는 이전 seed에서 모두 충돌)로
  보아 이번에는 `untestable`이 예상된다. 이는 정책 템플릿("층 최소치 미달 → 판단 불가")에서
  벗어난 것이다. rescue형 후보의 무회귀 층이 구조적으로 작다는 1차 검토 권고를 따랐다.
- **최소 효과크기**: 기준 대비 query 순증 ≥ max(2, ⌈0.25 × 거부 query 수⌉).
- **선택 순서**: 순증 큰 것 → 채택 query 많은 것 → 계획시간 P95 낮은 것 → attempts 적은 것(k3).
- **판정별 후속**: 선택됨 → 중단한다. 새 held-out(정책 v2의 절차 생성 지도, 기존 후보가
  거부하지만 A* 경로가 도달하는 query 포함)은 사용자 승인 뒤에 진행한다. 선택 없음 → 음성
  결과로 기록하고 이 입력에서 더 조정하지 않는다. 판단 불가·감사 무효 → 기록만 하고, 이
  스텝에서 재실행하지 않는다(비결정성 조사는 새 스텝).
- **감사 세부**: 실행과 재계획이 모두 `rescue=timeout`이면 경로가 같으므로 유효로 보고 구제
  실패로 센다. 후보별 timeout 수는 `decision.json`의 `rescue_timeouts`에 남는다. 감사 불일치는
  planner와 무관하게 실행 전체를 무효로 하므로, k6나 ablation 한 건의 불일치로 k3 판정도
  사라진다.
- Hybrid A*, ablation, seed 단위 수치는 보조로만 보고한다.

## 독립 검토

1차: `anthropic/claude-fable-5-2`, 사전 등록 커밋 `a0f295e`를 읽기 전용으로 검토했고 판정은
"수정 후 재검토"였다. 반영 내용은 다음과 같다.

- **P1-1**: 무회귀 조건과 기준 층 5개는 구조상 공허했다. 판정 분모를 거부 query로 바꾸고,
  회귀 검정 가능 층과 `untestable` 표시를 추가했다. 최소 효과를 거부 수에 비례시켰다.
- **P2-1**: 20 query 채택 분포, 의도하지 않은 사전 노출, 해석 제한 네 가지를 위에 공개했다.
- **P2-2**: 합성 근거를 `results/leadin_synthetic_check.py`로 커밋하고 재현 수치로 고쳤다.
  사전 등록 당시의 "18건 중 9건"은 목표 한 종류만 센 수치였다.
- **P2-3**: 구제 중 시간이 끝나면 TIMEOUT 대신 기존 결과를 반환하도록 바꾸고 합성 계획시간을 적었다.
- **P2-4**: 접합부 어긋남을 기록했다(코드 유지).
- **P2-5**: 감사에서 경로가 없을 때의 비교 오류를 고치고, 불일치 시 판정 무효를 규칙에 넣었다.
- **P2-6**: 계획 전 `protocol_start.json`을 기록하고 계획 오류의 빈 시간을 제외한다.
- **P2-7**: 구제 단계 시간 초과, `run`·감사 합성 smoke, 판정 분기 테스트를 추가했다.
- **P2-8**: 착수 승인 범위를 위에 기록했다.
- **P3**: 판단 불가 시 `eligible`을 False로 하고, P95가 None이면 정렬 뒤로 보내고, 기존 후보가
  실패한 경우를 `base_failed`로 표시하고, 지도 hash·import 경로를 기록하고, 쓰지 않는 값을 지웠다.

2차: 같은 모델이 `c6a3669`를 재검토했고 판정은 **"실행 가능"**(P1 없음)이었다.

- **P2-a**: 감사 재계획의 예외를 잡아 `planning_error`로 비교하도록 고쳤다.
- **P2-b**: 양쪽 timeout과 전체 무효 범위를 위 감사 세부에 적었다. `rescue_timeouts`·
  `audit_mismatches`를 decision에 추가했다.
- **P2-c**: 템플릿 이탈을 무회귀 항목에 적었다.
- **P2-d**: 판단 불가·감사 무효 시 이 스텝에서 재실행하지 않음을 명시했다(runner `FOLLOW_UP` 포함).
- **P2-e**: 실행 직전 같은 장비에서 `tests/test_leadin_rescue.py`를 실행하고 통과한 경우에만 실행한다.
- **P3**: fallback 주석을 고쳤다. 실행 전에 사전 등록 커밋 이후 코드 diff가 없음을 확인한다.
  gains를 거부 집합으로 제한하지 않는 점과 후보별 `tested` 표시가 아닌 점은 그대로 둔다
  (`untestable` 예상, 영향 작음).

이 반영(코드 변경 포함)을 커밋한 것이 최종 사전 등록이며, 그 커밋을 `--prereg-commit`으로 넘긴다.
