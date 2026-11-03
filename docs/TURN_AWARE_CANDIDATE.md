# 방향 변화 비용 사용자 플래너 후보 — 2026-11-03

## 구현과 고정 설계

`examples/turn_aware_planner.py:TurnAwareAStar`는 기존 A*에 위임하지 않고 직접
8-connected A*를 구현한다. 기존 clearance 비용 후보의 음성 결과 이후, 경로의
방향 변화 비용을 추가했을 때 같은 controller의 추종이 어떻게 달라지는지 확인할
개발 후보다. 현재 사용자 알고리즘이 별도로 제공되지 않아 이 후보를 준비했다.
새 알고리즘의 독창성이나 주행 성능 향상은 구현 자체로 주장하지 않는다.

상태는 `(row, column, incoming_direction)`이다. 같은 셀에 도착해도 진입 방향에
따라 다음 이동 비용이 달라지므로 각 방향을 별도 상태로 유지한다. 시작 상태만
별도 sentinel을 사용하고 실제 입력 `start.yaw`에서 첫 이동의 각도를 계산한다.
각 간선 비용은 다음과 같다.

```text
step_length_m + 0.20 m/rad × abs(wrapped(next_heading - previous_heading))
```

가중치 **0.20 m/rad**는 실험 전 고정한 개발 설정으로 90도 회전에 약0.314m를
추가한다. 결과를 보고 선택한 값이나 검증에서 최적화한 값은 아니다. 같은 코드의
`LengthOnlyAStar`는 가중치0인 ablation이며 이름은 `turn_aware_zero`이다.
두 클래스는 인자 없이 로드되고 dataclass config가 manifest에 기록된다.

대각선은 양쪽 직교 이웃이 모두 free일 때만 허용한다. 휴리스틱은 goal-cell까지
유클리드 거리(m)이며 추가 방향 비용이 비음수라서 일관적인 하한이다. 유한한 grid와
시간 제한 없는 실행에서는 연결된 goal-cell을 찾고 이 방향-state 그래프의 비용을
최소화한다. goal yaw와 실제 자동차 운동학을 제약하지 않는다. 탐색 상태 수는
최대 `8 × free cells + 1`이며 방향 비용이 없는 baseline보다 탐색이 늘 수 있다.
가중치0은 baseline A*와 최적 길이가 같지만 tie-breaking과 상태 표현이 다르므로
waypoint나 궤적의 완전한 일치까지 보장하지 않는다.

시작·목표는 입력 위치가 속한 셀의 중심으로 양자화한다. 반환 yaw는 outgoing edge의
방향이고 마지막은 incoming 방향이다(한 점 경로는 start yaw). 비용에는 첫 방향 변화도
포함되지만 분석기의 `total_absolute_turn_rad`는 resampled XY polyline의 내부 회전이라
첫 방향 변화와 다른 값일 수 있다. 경로 비용은 XY 길이와 구분한다.

이동은 점의 격자 연결성 기준이다. 차량 footprint, steering 한계·swept collision,
미끄러짐은 탐색에서 검사하지 않는다. 현재 개발 runner는 모든 planner와 주행에 같은
inflated grid를 사용한다. 아래 비교의 inflation0은 원본 물리 지도를 그대로 쓴다.
Hybrid A*의 사각형 footprint 제약과 이 점 탐색 표현은 동등하지 않으며, 실제 충돌은
공통 simulator에서 평가한다. timeout은 loop에서 확인하는 cooperative 예산이다.

## 사전 고정한 개발 비교

기존 `scenarios/demo.yaml` 한 지도에서 기존3종+후보+가중치0, seed0/1/2를 비교한다.
무잡음과 고정 잡음2조건으로 **총30 episode**이며 조건별 결과를 따로 저장한다.
잡음은 initial position0.02m, initial yaw0.02rad, steering0.01rad,
speed measurement0.02m/s이고 initial speed는0이다. 같은 seed가 모든 planner의
시간 step별 잡음을 맞춘다. 지도·차량·tracker·시간 제한·성공 기준은 기존 CLI 기본값이다.
계획은 조건별 planner당1회이고 seed에 재사용하므로 시간 표본을3회로 해석하지 않는다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/turn_aware_comparison.py --output-dir results/raw/turn_aware_20261103
```

runner는 결과 폴더가 존재하면 거부하며, 실행 전 `protocol.json`에 조건과
후보·runner hash 및 이 문서의 사전 설계 사본 `design_snapshot.md` hash를 남긴다.
각 조건에 experiment CSV/manifest, 첫 seed PNG,
기존 분석기의 episodes/planners/paired/clearance가 저장된다. 마지막으로 `summary.json`과
산출물 hash를 기록한다. 분석은 A* 기준이며 실패를 분모에서 빼지 않는다.

이는 이미 사용한 demo의 개발 비교로 연결·비용 효과·실패를 관찰하는 범위다.
최종 평가는 새 validation/evaluation split과 가중치·예산을 별도로 고정한 뒤 진행한다.
기존 회복v4 결과와 frozen 연구 결과는 이번 비교에 합치지 않는다.

## 구현 완료 후 검증

방향-state 독립 Dijkstra oracle과 비용/경로의 일치, start yaw의 경로 선택 영향,
가중치0의 최단길이, corner cutting·계획 실패·timeout·같은 셀 처리 및 공개 비교 CLI의
config 기록을 테스트한다. 구현 중 테스트/실험을 실행하지 않고 코드 작성이 끝난 뒤
관련 테스트와 전체 pytest, 위 개발 비교를 한 묶음으로 실행한다.

## 구현 후 일괄 실행 결과

6.1-sol이 코드·테스트·프로토콜 작성을 끝낸 뒤 관련 테스트1회 **8 passed (2.73s)**,
전체 pytest1회 **84 passed (3.74s)**, 고정 개발 비교1회30건을 묶어서 실행했다.
두 조건 모두 각 planner3/3 도달, 전체 **30/30 도달·충돌0·timeout0·계획실패0**이다.
PNG2장 생성/시각검토와 기존 analyze를 완료했다. 무잡음3 seed는 같은 실행의 반복이다.

고정 잡음 조건에서 지표는 다음과 같다. RMSE/완료시간은 성공3건 중앙값,
clearance는 실제 주행3건의 모든 기록 pose에서 얻은 최솟값이다.

| planner | 도달 | RMSE(m) | 완료시간(s) | 실제 최소 clearance(m) |
|---|---:|---:|---:|---:|
| Dijkstra | 3/3 | 0.08765 | 12.95 | 0.26693 |
| A* | 3/3 | 0.12881 | 12.85 | 0.28295 |
| Hybrid A* | 3/3 | 0.02483 | 12.50 | 0.01425 |
| 방향-state A* 0.20 | 3/3 | 0.08030 | 13.20 | 0.26693 |
| 방향-state 가중치0 | 3/3 | 0.12881 | 12.85 | 0.28295 |

무잡음 후보/A* RMSE는0.08086/0.12988m, 완료시간13.20/12.85s였다. 계획 XY 길이는
둘 다11.07107m였지만 resampled 내부 절대 회전합은4.71239→2.35619rad로 줄었다.
최대 이산 곡률은6.54242→7.68783/m로 커졌다. 가중치0과 A*는 이번 두 조건의
모든 paired 주행 지표 delta가0이다. 일반적인 경로 동일성을 뜻하지 않는다.

후보의 이 demo 추종 오차는 줄었지만 도달률 향상은 없고 완료시간과 실제 최소
clearance는 불리했다. 회전합을 줄이는 비용이 최대 곡률·안전 여유까지 개선하지는
않는다. 방향-state 탐색은32 nodes, baseline A*는21 nodes였다. 계획시간은 각1회
자체 보고값이라 실행속도 순위나 통계적 효과를 결론내리지 않는다.
계획 footprint clearance는 waypoint yaw의 영향을 받는다. baseline grid planner의
yaw0과 후보의 접선 yaw가 다르므로 그 수치 차이를 안전성 향상으로 해석하지 않는다.
실제 clearance 비교는 같은 simulator가 기록한 실제 yaw에서 계산했다.

실행 원본은 `results/raw/turn_aware_20261103/`에 보존한다. `protocol.json`과
`design_snapshot.md`는 실행 전 고정 설계를 보존하고 `artifact_sha256.json`은 완료
산출물 hash를 보존한다. 요약/프로토콜/설계 사본/hash의 공유용 복사본은
`results/analysis/turn_aware_20261103/`, PNG 복사본은
`results/figures/turn_aware_20261103/{clean,noise}.png`다. 원본을 이동하지 않았다.
raw는 ignore된 로컬 자료라 Git만으로 전체 경로·궤적을 복원할 수 없다.

다음 묶음은 고정값0.20을 유지한 채 새 validation/evaluation split과 실행 예산을
먼저 정의하고, validation의 실패 조건·trade-off를 분석하는 것이다. 현재 demo를
근거로 가중치를 재선택하거나 최종 성능 개선을 주장하지 않는다.
신규 split의 사전 설계와 단일 실행/봉인 규칙은
[TURN_AWARE_HOLDOUT.md](TURN_AWARE_HOLDOUT.md)에 정의했다.

## Astra 독립 검증

Astra는 랜덤 소형 격자100개에서 양의 가중치와 가중치0 총200건을 독립 Dijkstra
oracle과 대조했고 경로 비용·상태가 모두 일치했다(경로 없음8건 포함). 두 조건
manifest의 소스 hash 각39개, 원본 산출물 hash23개, 공유본/PNG와 분석 입력을
대조했다. 30건 모두 충돌 없이 목표0.5m 이내였고, weight0과 A*의6쌍 전체 주행
시계열이 일치했다. 저장 CSV의 RMSE·완료시간·clearance와 문서 수치도 일치했다.
휴리스틱·경로 복원·제약 문서화에 차단 결함 없이 최종 승인했다.
