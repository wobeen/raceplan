# 전체 연구 사이클 실행 보고 — 2026-10-13

## 범위와 결론

제안한 9개 단위의 **소규모 합성 지도 연구 사이클**을 구현하고 실행했다.
52개 테스트가 통과했다. 해상도/주행 간격 민감도, validation baseline,
clearance 비용 후보 선택, 설정 동결, 미사용 지도 평가와 비용 제거 ablation,
지도 단위 불확실성 및 실패 이미지, 원본을 포함한 재현 ZIP을 만들었다.

선택한 clearance A*는 기본 A*보다 위치/방향 도달률을 높이지 못했다.
성공한 개선 알고리즘을 개발했다고 주장하지 않는다. 보수적인 planning 표현,
목표 방향 처리, 실제 주행 clearance가 서로 다른 실패 원인임을 확인했다.

완전한 planner 동등성, 정확한 연속 기하 병목 추출, 대규모 통계 검증, 새로운
map family로의 일반화, 실차 검증까지 완료한 것은 아니다. 다음 개발은 새로운
validation/evaluation 분리에서 진행해야 하며 이번 evaluation은 다시 튜닝용
결과를 보고 '미사용' 평가라고 부를 수 없다.

## 1. 비교 공정성

`circle_planning_grid`는 rear-axle 기준 모든 yaw의 차량 footprint를 감싸는
원 반경에 셀 반대각선 길이를 더한 보수적 C-space를 만든다. grid planner는
이 지도에서 탐색하고, Hybrid A*는 원본 지도에서 회전 사각형을 검사한다.
모든 실제 주행과 clearance 평가는 원본 물리 지도를 사용한다.

이는 차량 부피를 무시한 점 탐색보다 보수적인 기준이며, **회전 사각형과
동등한 planning 표현은 아니다.** 원형 표현이 feasible passage를 제거할 수 있다.
특히 평가 gate에서 grid planner 실패는 이 보수성의 영향으로 해석해야 한다.

종료 규칙은 기존 controller의 위치 0.5 m 기준을 유지했다. 공통 사후 평가로
최종 yaw 오차 0.35 rad 이하를 추가해 `position_success`와 `pose_success`를
별도로 저장했다. Grid planner는 yaw 제약을 계획하지 않고 Pure Pursuit도
종단 yaw 제어가 없으므로 이 지표는 planner/controller 체계의 능력 차이를
드러낸다. yaw 기준을 만족하도록 controller를 평가 후 수정하지 않았다.

## 2. 해상도와 측정

동일 물리 gate 형상/query에서 격자 0.2/0.1/0.05 m, 별도 dt 0.1/0.05/0.025 s를
무잡음으로 비교했다. 잡음의 시간 간격 의존성을 혼합하지 않기 위함이다.
측정 간격 0.2/0.1/0.05 m도 동일 저장 경로에서 따로 비교했다.

0.2 m의 grid C-space에서는 경로가 막혔다. 0.1과 0.05 m도 RMSE가 다르므로
수렴을 주장하지 않는다. Grid polyline 최대 곡률은 측정 간격을 줄일수록
커지는 코너 특성이 있다. 0.1 m / dt 0.05 s / 측정 0.1 m를 계산 예산과
기존 설정 연속성에 따른 기준으로 고정했다. 민감도 점검은 gate query 1개에
한정되며 전체 family의 수렴 검증이 아니다.

## 3. 시나리오와 분리

Validation: gate/slalom/turn/heading 4개 지도, 지도당 2 query, seed 0/1/2.
Evaluation: 같은 4개 family의 **다른 형상** 4개 지도, 지도당 2 query,
seed 3/4/5/6/7. 해상도·차량·controller·planning timeout 3 s를 고정했다.
지도와 query 생성 규칙은 평가 전 소스에 정의했다. 평가 결과는 freeze 이후
처음 실행했다. 이는 family 내부 형상 변화 일반화이며 미지 family 평가가 아니다.

## 4. 설명 지표

기존 경로 길이/곡률/clearance/RMSE/조향 지표에 Q90 이산 곡률을 더했다.
비교 대상 planner의 선택 경로와 독립인 point A* reference 우회도와
widest-path 탐색의 whole-cell disk 지름/차량 폭을 계산했다.

후자는 grid route의 보수적 여유 하한이고 **정확한 연속 병목 폭이 아니다.**
유클리드 연속 공간의 정확한 병목 추출은 후속 확장이다. 지도와 경로 지표의
Pearson 관계는 case/planner별 seed 평균으로만 탐색적으로 기록했다.
case를 공유하므로 행들이 독립 표본이 아니며 상관을 인과로 해석하지 않는다.

추가로 합성 직사각형 지도에서는 시작/목표 사이 x slab마다 가장 넓은 free y
interval을 연속 좌표에서 구한 뒤 그 최솟값을 저장했다. 이 **수직 단면 병목 폭**은
raster와 독립이며 gate에서 정확히 validation 1.2 m, evaluation 1.0 m다.
0.2/0.1/0.05 m 해상도에서 값이 불변임을 테스트했다. 일반 지도에서 경로 연결성이나
임의 방향 최대 통과 폭을 보장하는 정의는 아니다. `analytic_map_widths.csv`에
proxy와 혼동하지 않도록 별도 필드로 저장하며 후보 선택에는 사용하지 않았다.


## 5. 실행과 데이터

| 단계 | episode 행 | 구성 |
|---|---:|---|
| 민감도 | 15 | 5조건 × 3planner × 무잡음 seed 1개 |
| Validation baseline | 72 | 8query × 3planner × 3seed |
| Validation 후보 | 48 | 8query × 2가중치 × 3seed |
| Evaluation + ablation | 200 | 8query × 5planner/변형 × 5seed |
| 합계 | 335 | 계획 실패 행 포함 |

계획은 seed와 독립이다. query/planner당 warmup 1회 후 validation은 3회,
evaluation은 5회 독립 반복해 timing.csv로 저장하고 첫 측정 경로를 seed 간
재사용했다. 요약에는 median/P95를 기록했다. 반복 시간이 seed 수만큼
중복되지 않으며 planning 시간은 사전 C-space/feature 계산 비용을 포함하지 않는다.
Clearance 후보 내부의 비용장 계산은 해당 planner 시간에 포함된다.

완료 단위마다 입력 설정·소스 hash·산출물 hash를 저장한다. 재개 시 동일성을
확인하고 불일치를 거부한다. 중단된 폴더는 번호를 붙여 보존한 후 다시 실행한다.
raw 폴더에는 실제 지도, 설정, 계획 경로, trajectory/clearance, 실패, 독립
timing과 complete 기록이 남는다. 총 29개 실행 단위가 있다.

## 6–8. 후보 선택, 미사용 평가와 ablation

Baseline validation에서 낮은 RMSE와 작은 안전 여유/충돌의 공존을 확인한 뒤
clearance 가중 비용 A* 하나를 후보로 골랐다. 비용은 edge length에
`1 + weight / (planning-grid clearance + resolution)`을 곱한 값이다.
이는 새 알고리즘의 독창성 주장이 아니라 고정 비용항 실험이다.

가중치 0.25/1.0을 validation에서 비교했다. 선택 규칙은 위치+방향 도달 수,
충돌 수, 성공 episode의 평균 RMSE 순서이며 동률이면 작은 가중치를 선호한다.
두 후보가 동률이라 0.25를 선택했다. 기본 A*와 도달 수는 3/24로 같았고
성공 RMSE는 후보가 더 나빴다. 개선되지 않았다는 사실도 freeze에 저장했다.

`freeze.json`을 평가 전에 작성하고 `evaluation_seal.json`에 hash를 보관했다.
평가 이후 가중치·설정은 바꾸지 않았다. 비용을 제거한 weight 0 ablation은
evaluation의 모든 episode 지표가 기본 A*와 일치함을 확인했다(계획 시간 제외).

| 평가 planner | 위치 도달 | 위치+방향 도달 | 충돌 | 계획 실패 |
|---|---:|---:|---:|---:|
| Dijkstra | 30/40 | 0/40 | 0 | 10 |
| A* | 30/40 | 0/40 | 0 | 10 |
| Hybrid A* | 20/40 | 15/40 | 20 | 0 |
| Clearance A* 0.25 | 30/40 | 0/40 | 0 | 10 |
| weight 0 ablation | 30/40 | 0/40 | 0 | 10 |

목표 방향을 요구하지 않는 응용에서는 위치 도달 결과를 별도로 봐야 한다.
이번 pose 기준으로 grid planner를 범용적으로 열등하다고 결론내리지 않는다.

Hybrid A*의 기본 A* 대비 paired pose 성공률 차이는 +0.375였다. 4개 지도를
cluster로 bootstrap한 percentile 구간은 [0, 0.75]로 매우 넓다. 다른 비교의
[0,0]은 모든 관측 지도에서 pose 실패한 데 따른 **bootstrap 퇴화**이며,
진짜 성공 확률이나 효과가 정확히 0이라는 뜻이 아니다. 작은 지도 수, 공유된
family, 종단 제어 미지원 때문에 이 구간은 탐색적 기술 통계로만 제시한다.

후보의 성공률 개선은 없었고 계획 비용도 늘었다. 평가에서 A* planning 중앙값
약 5.7 ms, 후보 약 145.2 ms였다. 이는 이번 환경의 기록이며 다른 머신의
시간이나 종합 preprocessing 포함 실행시간으로 일반화할 수 없다.

## 9. 재현과 산출물

```powershell
uv sync --python 3.13 --extra dev
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe results/research_all.py --name research_20261013
# 새 실행은 다른 name 지정
.venv/Scripts/python.exe results/research_all.py --name research_reproduction
```

전체 명령은 단계 순서를 지키고 완료 단위를 재개하며 표/그림과 ZIP을 만든다.
기존 freeze가 있으면 후보 선택을 다시 하지 않는다. 분석/그림/ZIP은 파생물이므로
재생성하고 raw 실험은 보존한다. 변경된 소스로 기존 실행을 재개하려 하면
hash 불일치로 중단되므로 새 name을 사용해야 한다.

그림 렌더러는 현재 Windows Malgun 폰트를 사용한다. 다른 OS에서는 폰트 경로
조정이 필요하다. 수치 결과의 타 환경 재현은 독립적으로 실행하지 않았고,
현재 환경에서 raw/source/freeze hash와 ZIP 내부 파일을 검증했다.

- raw: `results/raw/research_20261013/`
- 표/선택/봉인/검증: `results/analysis/research_20261013/`
- 이미지 4개: `results/figures/research_20261013/`
- 재현 ZIP: `results/packages/research_20261013.zip`
- ZIP에는 src/tests/docs/지도/실험 raw/표/그림/lockfile과 SHA256SUMS가 포함된다.

## 남은 연구 한계

1. grid disk와 Hybrid rectangle의 보수성이 다르다. 공통 heading-state footprint
   탐색이나 표현별 ablation을 해야 알고리즘 자체 효과를 더 분리할 수 있다.
2. 실제 연속 swept collision 검사는 아니다. dt 사이의 충돌을 보장하지 않는다.
3. 종단 yaw controller를 설계하지 않았고, 이번 pose 기준 결과를 본 뒤 고치지 않았다.
4. exact bottleneck, 큰 map suite, 새 family 평가, 더 많은 지도 기반 통계는 남아 있다.
5. 목표는 작은 연구 사이클 완결이며 논문 수준의 신규성·일반성 입증은 아니다.

이 한계들을 숨기지 않고 다음 사이클에서 새로운 평가 지도로 검증하는 것이 후속 방향이다.
