# 출발 lead-in 구제 후보 개발 비교 — 사전 등록 (2026-11-24, 정책 v2)

## 착수와 범위

사용자 지시(2026-11-24): "새로 만든 정책은 우선 브랜치 하나 파서 개발 연구 시작해".
브랜치 `research/policy-v2-curvature`에서 정책 v2([절차](COMMIT_PLAN.md),
[판정 템플릿](FEATURE_SCOPE.md), [봉인 기록](../results/README.md))의 첫 연구 스텝으로 진행한다.
이 스텝은 **개발 선택**이며 held-out 근거가 아니다. 선택된 후보가 있어도 새 held-out은
별도 사용자 승인 뒤에 진행한다.

## 문제와 사전 진단 (주행 없음)

`SmoothedLowClearance`(목표 clearance 0.30m)는 후처리 경로가 곡률 한계(1.4685/m) 또는
footprint 여유를 넘으면 원래 A* 경로로 되돌아가고, 그때 대부분 충돌한다. 아래 20개 노출
query에서 기존 후보만 **계획(주행 없음)**해 최대 곡률 위치를 확인했다. 곡률 거부 6건 중 5건의
최대 곡률이 출발 후 0–0.3m에 있었다. 시작 yaw 고정 구간과 바로 앞 장애물 때문에 출발 직후
급회전이 강제되는 것이 주원인이다.

**사전 등록 전 시험(기록)**: 처음 구상한 "위반 구간 국소 강성 증가"(위반 지점 ±0.5m의
2차 차분 가중치 ×4, 최대 3라운드)를 같은 20 query에서 **계획만** 해 보았다. 곡률 거부 6건이
모두 footprint 거부로 바뀌어 구제 0건이었고, 원래 채택되던 1건을 잃었다. 정책 v2는 사전
등록 전 판단 데이터의 주행을 금지하지만, 이 계획 전용 시험도 개발 입력의 정보를 본 것이므로
여기 기록한다. 이 구상은 폐기했고 코드는 남기지 않았다.

이후 후보 설계와 파라미터는 **합성 격자에서만** 정했다. 합성 격자는 외벽이 있는 10.4×7.2m
지도에 시작 앞 0.9–1.7m의 수직 벽을 둔 것이다(테스트 `wall_ahead`와 같은 종류). 기존 후보가
곡률로 거부한 합성 18건 중 9건을 구제했다. 직선 lead-in만 쓰는 ablation은 0건이었다.
합성에서도 주행은 하지 않았다.

## 후보 (`examples/leadin_rescue_planner.py`)

1. 기존 `SmoothedLowClearance`를 그대로 실행한다. 채택되면 **그 결과를 바꾸지 않고** 반환한다.
2. 거부된 경우에만 구제한다. 시작 자세에서 곡률 9개(±0.9×한계 균등, 0 포함)와 길이 3개
   (0.6/1.0/1.4m)의 등곡률 호를 만든다. 호 위 모든 표본에서 footprint 여유가 0.02m 이상인
   것만 남긴다.
3. 남은 호마다 호 끝에서 목표까지 A*를 계획하고, 호 끝 heading과 A* 진행 방향(0.5m 앞)의
   차이, 그다음 총 길이 순으로 정렬한다.
4. 상위 `attempts`개에 대해 호 점을 고정하고 나머지를 기존과 같은 방식(반발 0.30m,
   가중치 100, 100회)으로 평활화한다. 기존과 같은 검증(0.05m 간격 footprint 여유 0.02m,
   곡률 한계)을 통과한 첫 경로를 반환한다. 모두 실패하면 기존 결과(A* 경로)를 반환한다.

| 이름 | 역할 | 설정 |
|---|---|---|
| `leadin_rescue_k3` | 후보 | 길이 0.6/1.0/1.4m, attempts 3 |
| `leadin_rescue_k6` | 후보 | 길이 0.6/1.0/1.4/1.8m, attempts 6 |
| `leadin_straight` | ablation, 선택 불가 | 곡률 0만, attempts 3 |

구조상 기존 후보가 채택한 query에서는 경로가 같으므로 차이가 날 수 없다. 차이는 기존 후보가
A* 경로로 되돌아간 query에서만 생긴다.

## 데이터와 실행

- 입력: 이미 노출된 20 query. `turn_aware_holdout_20261103`의 validation·evaluation 8개와
  `smoothing_holdout_20261123`의 12개다(커밋된 `results/analysis/**/inputs` 사본).
- seed 11/12/13, 잡음은 이전 연구와 같다(위치 0.02m, 초기 yaw 0.02rad, steering 0.01rad,
  speed 0.02m/s). inflation 0, 계획 timeout은 시나리오 값 2s다.
- planner: A*, Hybrid A*, 기준 `smoothed_low_clearance`, 후보 2개, ablation. 총 360 episode.
- runner `results/leadin_rescue_development.py`는 추적 파일이 dirty이거나 사전 등록 커밋이
  HEAD의 조상이 아니면 실행을 거부한다. 실행 커밋, `uv.lock` hash, Python·OS, POSIX 경로 hash를
  `protocol.json`에 기록한다. 채택·구제 여부는 실행 뒤 결정적 재계획으로 얻고, 저장된 경로와
  pose 단위로 완전히 같아야 한다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/leadin_rescue_development.py `
  --output-dir results/raw/leadin_rescue_development_20261124 --prereg-commit <사전 등록 커밋>
```

## 판정 규칙 (runner의 `decide`가 그대로 계산)

- **분석 단위**: query. 3 seed 중 2개 이상 도달하면 그 query를 도달로 본다.
- **기준과 층**: 무회귀 기준은 `smoothed_low_clearance`와 A*다. 기준 후보가 도달한 query가
  5개 미만이면 "판단 불가"다.
- **적격**: 기준 후보 또는 A*가 도달한 query를 하나도 잃지 않고, 기준 후보 대비 query 순증이
  2개 이상이다(20 query의 10%).
- **선택 순서**: 순증 큰 것 → 채택 query 많은 것 → 계획시간 P95 낮은 것 → attempts 적은 것(k3).
- **판정별 후속**: 선택됨 → 중단하고 새 held-out(정책 v2 절차 생성 지도)은 사용자 승인 후.
  선택 없음 → 음성 결과로 기록하고 이 입력에서 더 조정하지 않음. 판단 불가 → 기록만.
- Hybrid A*, ablation, seed 단위 수치는 보조로만 보고한다.

## 독립 검토

사전 등록 커밋 뒤 실행 전에 읽기 전용 독립 검토를 받고, 모델·지적·반영 여부를 이 절에 적는다.
