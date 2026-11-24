# 검증 여유 상향 lead-in 구제 개발 비교 — 사전 등록 (2026-11-25, 정책 v2)

## 착수와 범위

사용자 지시(2026-11-25): "1번 가설로 진행하고 정책 v2는 이 브랜치에서 계속 시험해". 1번 가설은
[직전 스텝](LEADIN_RESCUE_DEVELOPMENT.md)의 결론, "경로 검증 여유를 추종 오차 이상으로 둔다"이다.
브랜치 `research/policy-v2-curvature`에서 정책 v2 절차(사전 등록 → 독립 검토 → 1회 실행 →
결과 커밋)를 따른다. 이 스텝은 **개발 선택**이며 held-out 근거가 아니다.

## 가설과 파라미터 고정 근거

직전 스텝에서 구제 경로의 footprint 여유는 0.030–0.048m였다. 같은 episode의 추종 RMSE는
0.034–0.047m였고 9개 모두 충돌했다. 새 입력이 생기기 전에, 직전 실행(노출 자료)에서 도달한
`smoothed_low_clearance` 36 episode의 **최대 추종 오차**를 집계했다. 중앙값은 0.076m,
90백분위는 0.102m, 최댓값은 0.113m였다. 이를 근거로 검증 여유를 두 값으로 고정했다.

| 이름 | 역할 | 내용 |
|---|---|---|
| `margin_rescue_08` | 후보 | 모든 검증(평활화 경로, lead-in 호)의 footprint 여유 0.08m, 나머지는 `leadin_rescue_k3`와 같음 |
| `margin_rescue_11` | 후보 | 같은 구조, 여유 0.11m |
| `margin_only_08` | ablation, 선택 불가 | 여유 0.08m 후처리만, lead-in 구제 없음 |
| `smoothed_low_clearance` | 기준 | 여유 0.02m 기존 후처리 |
| `leadin_rescue_k3` | 보조 | 직전 스텝 후보(여유 0.02m) |

구현은 `examples/margin_rescue_planner.py`다. 커밋된 `leadin_rescue_planner.py`와
`smoothed_astar_planner.py`를 내용 hash로 불러와 여유만 바꾸며, 두 파일은 수정하지 않는다.
여유를 올리면 기존 후보가 채택하던 경로도 거부되어 A* 경로로 돌아갈 수 있다. 그래서 직전
스텝과 달리 기준 대비 **회귀가 실제로 일어날 수 있고**, 무회귀 조건은 검정력을 가진다.

## 새 개발 입력 (절차 생성)

이번 가설은 직전 20 query에서 나왔으므로 그 입력을 다시 쓰지 않는다. runner의 `generate`가
커밋된 seed 범위 **1000–1011**에서 지도 12개·query 24개를 실행 시점에 만든다.

- 10.4×7.2m, 해상도 0.2m, 0.2m 외벽이다. family는 seed 순서로 staggered_windows,
  offset_islands, slalom_walls를 돌아가며 4개씩 만든다. 각 family의 벽·섬 위치와 크기, 창 높이,
  위아래 배치를 seed의 난수로 정한다. 범위는 `results/margin_rescue_development.py`의
  `interior`에 있다.
- query는 지도마다 2개다. (1.2, y)→(9.2, y′)이고, y는 [1.4, 1.8]·[5.4, 5.8]에서 0.1m 단위로
  뽑으며, 낮은→높은과 높은→낮은 방향이 하나씩이다. 시작·목표 footprint가 충돌하면 같은 난수열로
  다시 뽑는다.
- seed 2000 이상은 이후 held-out용으로 예약하며, 생성기가 거부한다. 테스트 smoke는 개발 범위
  밖의 seed 1999만 쓴다.
- 신규성: Git에 커밋된 지도·시나리오 YAML 전체와 exact v2 identity, 같은 격자 크기의 점유 셀
  IoU를 비교한다. exact 중복이나 IoU ≥ 0.9가 있으면 실행을 거부한다. 사전 등록 테스트는
  생성된 지도만 검사하며(계획·주행 없음), 중복 0·최대 IoU 0.9 미만을 확인한다.
- 지도 생성기는 저자가 이번 가설의 결과를 보기 전에 정했다. 생성된 지도 자체는 계획·주행 없이
  테스트에서 신규성만 확인했다.

## 실행

seed 11/12/13, 잡음은 이전과 같다. planner는 A*, Hybrid A*, 기준, 직전 후보, 후보 2개,
ablation으로 총 24 query × 3 seed × 7 = 504 episode다. runner는 다음을 한다.

- 추적 파일이 dirty이거나 사전 등록 커밋이 HEAD의 조상이 아니면 거부한다.
- 계획 전에 `novelty.json`과 `protocol_start.json`을 쓴다. 기록 항목은 실행 커밋, `uv.lock` hash,
  Python·OS, import 경로, 생성 입력 hash다.
- 실행 후 후처리 planner 5개를 결정적으로 재계획해 저장 경로와 pose 단위로 비교한다.
  불일치가 하나라도 있으면 `invalid_audit`이다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/margin_rescue_development.py `
  --output-dir results/raw/margin_rescue_development_20261125 --prereg-commit <사전 등록 커밋>
```

## 판정 규칙 (runner의 `decide`)

- **분석 단위**: query. 3 seed 중 2개 이상 도달하면 그 query를 도달로 본다.
- **기준과 층**: 기준 `smoothed_low_clearance`가 도달한 query가 6개 미만이면 "판단 불가"다.
  A* 도달 query도 무회귀 대상이다.
- **적격**: 기준 또는 A*가 도달한 query를 하나도 잃지 않고, 기준 대비 query 순증이
  max(2, ⌈0.1 × 24⌉) = 3 이상이다.
- **선택 순서**: 순증 → 채택 query 수 → 계획시간 P95 → 작은 여유(0.08).
- **판정별 후속**: 선택됨 → 중단하고, seed 2000 이상의 held-out은 사용자 승인 뒤에 진행한다.
  선택 없음 → 음성 결과로 기록하고 이 입력에서 더 조정하지 않는다. 판단 불가·감사 무효 →
  기록만 하고 재실행하지 않는다.
- 직전 후보, Hybrid A*, ablation, seed 단위 수치는 보조로만 보고한다.

## 독립 검토

사전 등록 커밋 뒤 실행 전에 읽기 전용 독립 검토를 받고, 모델·지적·반영 여부를 여기에 적는다.
