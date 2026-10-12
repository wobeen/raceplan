# 선행연구와 연구 공백

> 조사일: 2026-10-12  
> 범위: 경로계획 벤치마크, Hybrid A* 비용 개선, planning–control 통합,
> 환경 난이도 및 적응형 planning

이 문서는 초기 범위 조사 결과다. “최초” 또는 “완전한 신규성”을 주장하기
위해서는 IEEE Xplore, Scopus, Web of Science 및 Google Scholar에서 검색식과
포함·제외 기준을 고정한 체계적 문헌조사가 추가로 필요하다.

## 1. 주요 선행연구

| 연구 | 주요 기여 | RacePlan과 겹치는 부분 | 확인된 범위의 한계 |
|---|---|---|---|
| PathBench (2022) | 고전·학습 planner의 통합 개발·시각화·benchmark, ROS 확장 | Dijkstra/A*, 공통 인터페이스, 다중 지도, 길이·시간·성공률·clearance | 주요 비교가 point-mass grid 환경이며 자동차형 동일-controller 폐루프 비교가 중심은 아님 |
| Benchmarking Metric Ground Navigation (2020) | 환경 난이도 지표와 300개 환경, 실제 로봇 검증 | 장애물 거리·가시성 등 지도 난이도 정량화 | 특정 planner 비용함수의 조건 적응과 Hybrid A* 개선이 중심은 아님 |
| F1TENTH Survey & Benchmarks (2024) | 분절된 F1TENTH 연구의 방법 정리와 baseline | F1TENTH, 직접 비교 필요성 | 개별 cost와 고정 controller의 인과적 비교보다 넓은 survey 성격 |
| Improved Analytic Hybrid A* (2022) | 길이·조향·조향 전환·Voronoi 안전 비용으로 analytic expansion 개선 | 안전–길이 교환관계, Hybrid A* 비용 개선 | 개선 범위가 analytic expansion에 집중되고 폐루프 controller 분리평가가 제한적 |
| Path-Tracking Hybrid A* + MPC (2024) | 기준 경로 편차 비용, 곡률 제약, full-body collision, MPC 추종 | planner와 실제 추종 성공의 연결 | 농업 기준 경로 smoothing 및 제안 MPC가 함께 바뀌어 일반적인 planner–controller 분리가 어려움 |
| Direction-Guided Hybrid A* (2025) | steering-change 및 방향 가이드 비용, 구간별 heuristic weight | 동적 가중치, 조향 부드러움 | 온실형 수작업 지도와 경험적 파라미터 중심; 미사용 지도 일반화 검증이 핵심은 아님 |
| Hybrid A* + Lemming Optimization (2025) | 길이·곡률·장애물 거리 목적을 이용한 파라미터 최적화 | 다목적 최적화 | 목적항 자체는 기존 항의 가중합이며 controller 기반 추종 실패를 직접 목적화하지 않음 |
| Integrated Planning/Tracking Evaluation (2026) | planner 설정, tracker 비교, PID 민감도와 여러 지도 평가 | planning–tracking 통합 평가와 PID | A* 설정 및 tracker 선정 중심; 자동차형 세 planner와 지도 난이도 조건부 정책이 중심은 아님 |
| Adaptive Voronoi Corridor Hybrid A* (2026) | 환경 topology와 차량 회전반경으로 corridor·heuristic 구성 | 복잡 환경 적응, 안전거리, 계산 효율 | corridor 기반 특정 해법이며 동일 controller의 폐루프 실패 모델은 아님 |
| Continuous-Curvature Planning + NMPC (2024) | 동일 NMPC에서 CC와 Reeds–Shepp reference의 추종 차이 검증 | 같은 controller로 경로 기하 효과 분리 | parking과 특정 경로 family 중심; map complexity에 따른 planner 선택은 다루지 않음 |

## 2. 반복해서 나타난 한계

### 2.1 비용항은 많지만 가중치 선택의 일반화 근거가 약함

길이, 곡률, steering, steering change, reverse, clearance 비용은 이미 널리
사용된다. 여러 연구에서 가중치를 파일럿 또는 경험적으로 정한 뒤 같은 종류의
지도에서 평가한다. 따라서 비용항을 하나 더 추가하는 것보다, 가중치 결정 규칙을
검증 지도에서 만들고 미사용 지도에서 고정 검증하는 것이 중요하다.

### 2.2 환경 복잡도를 정성적으로 표현하는 경우가 많음

`simple`, `complex`, `cluttered`, `narrow` 같은 명칭은 자주 사용되지만 차량 폭,
최소 병목, obstacle clearance, 우회도, 요구 곡률로 정규화하지 않으면 다른
논문의 결과와 직접 비교하기 어렵다. 환경 난이도 benchmark 연구는 존재하지만,
그 지표를 자동차형 Hybrid A* 비용 선택과 폐루프 실패에 연결한 검증은 별도 문제다.

### 2.3 계획 지표와 폐루프 주행 지표가 분리됨

많은 planner 개선 연구는 planning time, path length, smoothness, node count를
주로 평가한다. 반대로 controller 연구는 이미 주어진 reference path의 tracking
error를 평가한다. 같은 controller에서 planner만 바꾸어 path geometry가 collision,
RMSE, steering saturation을 어떻게 바꾸는지 분리하는 실험은 상대적으로 제한적이다.

### 2.4 planner와 controller를 동시에 바꾸어 원인 분리가 어려움

제안 planner와 제안 MPC 또는 local planner를 함께 사용하면 전체 성능은 좋아질
수 있지만 개선 원인이 global path, smoothing, speed profile, controller 중 어디에
있는지 분리하기 어렵다. 고정 tracker/PID baseline과 후속 controller sensitivity를
분리할 필요가 있다.

### 2.5 평균 성능이 어려운 사례를 가림

전체 평균 성공률과 평균 path length만 보고하면 narrow passage, goal-heading,
dead-end 같은 구조적 실패가 묻힌다. 환경 특성별 계층화, 최악 분위수, 실패 유형,
동일 map/query/seed 짝비교가 필요하다.

### 2.6 평가 지도에서 다시 튜닝할 위험

가중치를 결과가 잘 나올 때까지 평가 지도에 맞추면 일반화가 아니라 지도별
과적합이다. validation/test 지도 분리와 사전 고정된 선택 규칙이 필요하다.

### 2.7 충돌 모델과 종료 조건이 planner마다 다를 수 있음

격자 planner의 obstacle inflation, Hybrid A*의 oriented footprint, goal-cell 도달,
goal-pose tolerance가 다르면 path length와 success rate를 그대로 비교하기 어렵다.
공통 물리 기준과 차이를 명시한 metric normalization이 필요하다.

### 2.8 공개 재현 자산이 항상 충분하지 않음

코드가 공개되어도 지도 seed, 실패 episode, raw CSV, controller 설정, timing 환경,
분석 스크립트가 모두 제공되지 않으면 결과 재현과 새 planner 추가가 어렵다.

## 3. RacePlan이 노릴 수 있는 연구 공백

가장 방어 가능한 질문은 다음과 같다.

> 차량 크기로 정규화한 지도 난이도와 계획 경로의 기하 특성이 고정 controller의
> 폐루프 실패를 얼마나 설명하며, 검증 지도에서 학습·설계한 조건부 planner 또는
> 비용 선택 규칙이 미사용 지도에서 안전성과 추종성을 개선할 수 있는가?

이 질문의 차별점은 새 cost term 하나가 아니라 다음 결합에 있다.

1. 자동차형 로봇과 full-body collision
2. 동일 tracker/PID로 planner 효과 분리
3. 병목 폭/차량 폭, 우회도, obstacle density, 요구 곡률의 명시적 측정
4. path geometry와 closed-loop failure의 연결
5. validation map에서 만든 규칙을 held-out evaluation map에 고정 적용
6. 평균뿐 아니라 worst-case와 실패 유형 평가
7. 동일 map/query/noise seed의 paired comparison
8. raw results, maps, configs, failures를 포함한 공개 재현 pipeline

## 4. 제안 비교군

- Dijkstra
- A*
- distance-only Hybrid A*
- 모든 지도에서 동일 가중치를 쓰는 fixed-cost Hybrid A*
- 지도 특성으로 가중치를 선택하는 complexity-conditioned Hybrid A*
- 지도 특성으로 planner 자체를 선택하는 selector

단순 adaptive weight만으로 신규성을 주장하지 않는다. obstacle density나 goal
distance로 heuristic을 바꾸는 연구가 이미 있으므로, 조건 변수·선택 규칙·held-out
검증·폐루프 목적의 조합이 기존 방법과 어떻게 다른지 명시해야 한다.

## 5. 권장 평가 설계

### 지도 특성

- obstacle density
- minimum bottleneck width / vehicle width
- reference-path length / straight-line distance
- required heading change per metre
- goal-heading constraint
- dead-end 및 homotopy class 수

### 일차 결과

- collision-free goal reach rate
- tracking RMSE / vehicle width
- steering saturation ratio
- minimum clearance / vehicle width
- planning-time 95th percentile와 timeout rate

### 분석

- 동일 조건 paired comparison
- map family 및 difficulty stratum별 결과
- median, IQR, confidence interval, effect size
- worst 10%와 실패 유형
- 비용항/특성/selector ablation
- validation에서 고정한 뒤 held-out map 평가

## 6. 현재 결론

- 단순 세 planner 비교: 신규성 낮음
- 곡률·조향·clearance 비용 추가: 신규성 낮음
- 경험적 다중 가중치 탐색: 신규성 낮음
- ROS 연결과 PID 추종: 단독 신규성 낮음
- 환경 난이도 지표: 기존 benchmark가 존재
- **지도 난이도 → 경로 기하 → 고정-controller 폐루프 실패 → 조건부 선택 규칙**을
  held-out map에서 검증하는 전체 구조: 추가 정밀 검색이 필요하지만 가장 유망함

## 7. 핵심 참고문헌

- PathBench: https://arxiv.org/abs/2203.03092
- Benchmarking Metric Ground Navigation: https://arxiv.org/abs/2008.13315
- F1TENTH survey and benchmarks: https://arxiv.org/abs/2402.18558
- Improved Analytic Expansions in Hybrid A*: https://doi.org/10.3390/app12125999
- Path-Tracking Hybrid A*: https://arxiv.org/abs/2411.14086
- Directional Guidance and Segment Weighting: https://doi.org/10.3390/app152212298
- Hybrid A* with Lemming Optimization: https://doi.org/10.3390/app15147734
- Integrated Planning and Tracking Evaluation: https://doi.org/10.1109/ISCAIT69154.2026.11477394
- Continuous-Curvature Planning and Control: https://arxiv.org/abs/2405.06290
- Adaptive Voronoi Corridor Hybrid A*: https://doi.org/10.1109/ISCER70245.2026.11681029
