# 목표 방향 종료 조건 진단

SimulationConfig.goal_yaw_tolerance를 추가했다. 기본값 None은 기존 위치 종료를
유지하고, 0보다 크고 pi 이하인 값을 주면 위치와 방향을 동시에 만족해야
REACHED가 된다. 각도는 wrap하며 경계 비교에는 1e-12 rad 오차를 허용한다.
이 옵션은 방향 제어기나 감속 제어기를 추가하지 않는다.

## 실험

기존 validation의 8개 질의, 3 planners, seeds 0/1/2, 두 종료 정책으로
144건을 실행했다. 각 planner/query의 경로를 한 번 계획해 공유했고 차량,
제어기, 물리 지도, 노이즈는 동일하다. 두 정책에서 먼저 종료하는 시점까지
모든 trajectory sample이 정확히 일치함을 assertion으로 검증했다.
위치 허용 오차는 0.5 m, 방향 허용 오차는 0.35 rad다.

| planner | pose 성공: 위치 종료 → pose 종료 | 충돌: 위치 종료 → pose 종료 |
|---|---:|---:|
| Dijkstra | 3/24 → 10/24 | 0/24 → 14/24 |
| A* | 3/24 → 5/24 | 0/24 → 19/24 |
| Hybrid A* | 6/24 → 10/24 | 9/24 → 14/24 |

두 조건 모두 성공은 위치+방향으로 다시 평가했다. 시간초과와 계획실패는
이번 실행에서 모두 0건이다. 종료를 늦추면 일부는 방향도 맞추지만 나머지는
충돌한다. 따라서 단순 종료 조건 강화는 안전한 개선책이 아니다.
다음 구현은 목표 접근 감속 및 목표 방향에 맞는 종단 경로/추종 제어이며,
전진 차량의 최소 회전 반경과 충돌 제약을 고려해야 한다.

기존 validation 재사용 진단이다. 새로운 미사용 지도 검증이나 일반적인
planner 우열의 근거로 해석하지 않는다. 이전 평가 ZIP과 raw는 수정하지
않았다. simulator 소스가 바뀌었으므로 이전 연구 실행의 hash 기반 재개는
거부되는 것이 정상이며 이전 소스 재현에는 보존된 ZIP을 사용한다.

## 검증과 산출물

- 전체 pytest: 58 passed. 잘못된 허용값, 기본값 호환, 각도 wrap, 경계,
  위치와 방향 동시 만족을 검증했다.
- results/goal_termination_diagnostic.py: 진단 실행 및 이미지 생성.
- results/analysis/goal_termination_20261013/: manifest, episodes, trajectories,
  summary JSON. manifest에 설정과 소스 hash를 저장했다.
- results/figures/goal_termination_20261013.png: 비교 그림.
- pre_boundary_fix 폴더는 경계 수정 전 첫 실행을 보존한 것으로 결과가 같다.

명령: `.venv/Scripts/python.exe results/goal_termination_diagnostic.py`.
기존 결과 폴더가 있으면 덮어쓰지 않고 실패한다.
