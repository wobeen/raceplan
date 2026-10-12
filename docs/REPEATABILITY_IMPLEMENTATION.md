# 반복 실험 구현 점검

2026-10-12 — 사용자 승인 후 40 tests passed 및 두 지도 파일럿 완료.

## 설계

- 고정 지도는 `map_seed: null`, 생성 지도 seed는 provenance로만 기록한다.
- simulation seed는 planner에 전달하지 않는다. planner별 계획 1회를 seed 간
  재사용하므로 계획 시간 반복 측정과 주행 잡음 반복을 혼동하지 않는다.
- 모든 planner의 실제 출발 pose는 scenario.start로 통일한다.
- 초기 위치·방향·속도, 조향 actuation, 속도 measurement 잡음은 Gaussian이다.
  초기 상태/조향/속도 측정의 PCG64 stream을 분리하고 episode마다 reset한다.
- 초기 속도는 0 주변 잡음을 속도 한계로 clip한다. 따라서 경계 근처 실제
  분포는 정규분포가 아니다. 조향도 actuator 한계로 clip한다.
- 잡음 크기는 CLI에서 설정하고 기본값은 모두 0이다. dt 변경 시 동일한
  물리 잡음 강도를 유지하는 모델은 이번 범위에 포함하지 않는다.
- summary와 trajectory는 episode_id로, 계획 waypoint는 plan_id로 연결한다.
  ID 유일성 범위는 batch 파일 안이며 batch 간 결합에는 출력 파일 식별자를 쓴다.
- 계획 실패도 seed별 summary를 남긴다. 주행 실패는 종료까지 trajectory를 남긴다.
- 설정, map/source hash, Python/NumPy 버전을 manifest에 저장한다. 소스 자체나
  지도 파일을 복제하는 archive 기능은 없으므로 재현 시 해당 버전을 보관해야 한다.

## 실행한 검증 범위

1. 기존 회귀 테스트 및 seed 필드 마이그레이션 확인.
2. 같은 seed의 trajectory 일치, 다른 seed의 주행 변화, 무잡음 seed 독립성.
3. planner 호출 횟수·입력의 seed 독립성과 summary/trajectory/path 연결 확인.
4. 계획 실패 및 초기 충돌 저장 확인.
5. demo와 추가 소형 validation 지도에서 무잡음 및 seed 0/1/2 파일럿.

파일럿 수치는 개발 점검값이며 held-out evaluation 또는 연구 결론으로 사용하지 않는다.


## 파일럿 결과

- 지도: demo-gap, validation-open (수작업 CC0 소형 지도, 각 query 1개).
- 세 planner × simulation seed 0/1/2 × 두 지도 × 무잡음/잡음 = 36 episode.
- 잡음 조건 18 episode를 다시 실행해 총 54회 주행. 모두 충돌 없이 도달.
- 재실행 trajectory 및 path CSV가 바이트 단위로 일치했다.
- 무잡음과 잡음 조건의 path CSV도 일치했다. planning time은 재현 비교에서 제외했다.
- 잡음 표준편차: 초기 위치 0.02 m (각 축), 방향 0.01 rad, 속도 0.01 m/s,
  조향 0.01 rad, 속도 측정 0.02 m/s. 검증용 임시값이며 보정된 값이 아니다.
- 회귀 테스트에서 no_path, timeout, 초기 collision 저장 및 기존 파일 보호 확인.

| 지도 | 조건 | planner | RMSE 범위 (m, seed 0/1/2) |
|---|---|---|---|
| demo | zero | dijkstra | 0.08645–0.08645 |
| demo | zero | astar | 0.12988–0.12988 |
| demo | zero | hybrid_astar | 0.02500–0.02500 |
| demo | noise | dijkstra | 0.08426–0.08992 |
| demo | noise | astar | 0.12674–0.13582 |
| demo | noise | hybrid_astar | 0.02476–0.02665 |
| validation_open | zero | dijkstra | 0.00000–0.00000 |
| validation_open | zero | astar | 0.00000–0.00000 |
| validation_open | zero | hybrid_astar | 0.01352–0.01352 |
| validation_open | noise | dijkstra | 0.00298–0.00619 |
| validation_open | noise | astar | 0.00298–0.00619 |
| validation_open | noise | hybrid_astar | 0.01397–0.01506 |

각 9-episode batch는 이번 환경에서 약 0.32–0.69초였다. 예열·반복을 통제한
planning 시간 benchmark가 아니므로 알고리즘 속도 비교에 사용하지 않는다.

## 해석과 다음 범위

- demo에서는 Hybrid A*의 RMSE가 낮지만 열린 직선에서는 grid planner의
  RMSE가 더 낮다. 이 소수 query로 일반적인 우열이나 지도 난이도 효과를 주장하지 않는다.
- 파일럿에 실패가 없어 실패율 추정과 failure-condition 분석에는 부족하다.
  좁은 통로·급커브·목표 방향 제약 query를 추가하는 것이 다음 실험 설계 대상이다.
- 실패 분류는 planning_status와 simulation_status를 분리한다. 계획 실패,
  초기 collision(time=0), 주행 collision(time>0), timeout, reached를 구분한다.
- 후속 지표 후보: 실제 경로 길이, 공통 간격 재표본화 곡률, footprint clearance,
  차량 폭 정규화 병목 폭, 장애물 밀도. 현재 path_cost_m와 RMSE만으로 인과를 추론하지 않는다.
- 현재 map_seed는 생성기의 입력으로 사용되지 않으며 고정 파일 hash가 지도를 식별한다.

## 재실행 및 산출물

프로젝트 루트에서 새 출력 디렉터리를 지정한다.

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe results/pilot_repeatability.py --output-dir results/raw/pilot_rerun
```

원본은 `results/raw/pilot_20261012/`에 보관했다. 각 batch에 summary,
trajectory, paths, manifest와 공통 verification.json이 있다. raw 결과는 기존
.gitignore 정책상 커밋 대상에서 제외되며, 이 문서와 재실행 스크립트는 추적 대상이다.
