# 작업 인계 — 2026-10-13

## 사용자 확정 사항

- 한국어로 보고. 구현 단위마다 테스트/실험 후 결과 이미지와 분석을 제공한다.
- 테스트는 추가 승인 없이 진행. 커밋과 staging은 사용자가 직접 한다.
- 성공은 충돌 없이 목표 위치 0.5m 이내 진입. yaw는 참고값이다.
- 기존 변경 및 frozen 원본은 보존한다. 이전 방향 필수 실험과 현재 기준을 혼합하지 않는다.

## 환경과 현재 상태

Windows PowerShell, `C:/Users/sinub/OneDrive/Desktop/raceplan`.
실행 `.venv/Scripts/python.exe`, 테스트 `-m pytest -q`: 마지막 71 passed.
Python313 이전 경로 경고가 출력되지만 실행/검증은 성공한다.
README와 docs/OBSTACLE_GUARD_20261013.md가 현재 기준이다.

세 planner(Dijkstra/A*/Hybrid A*), Pure Pursuit/PID/bicycle simulator,
paired seed/noise, geometry/clearance 분석, 통로 폭 실험, 소규모 연구 사이클을 구현했다.
pose는 후륜 축 중심이고 전륜 조향이며 차량 전체 직사각형을 충돌 검사한다.

- 과거 연구: 335 records, clearance A* .25 후보 개선 없음. pose scoring이었다.
  results/packages/research_20261013.zip에 당시 소스/원본 데이터 포함.
- SimulationConfig.goal_yaw_tolerance: 기본 None. 위치만으로 성공 판단.
- PurePursuitConfig.approach_distance/approach_min_speed: 경로 끝 접근 감속 옵션.
- run_episode(..., obstacle_guard=ObstacleGuardConfig()): 현재 몸체 clearance 및
  고정 조향 예측으로 속도 제한/제동. true state와 완전한 정적 지도 사용.
  기본은 꺼져 있으며 기존 CLI에 자동 적용하지 않았다.

## 최신 결과

results/obstacle_guard_diagnostic.py: validation 8 queries × 3 planners ×
3 seeds × 기존/guard = 144건. 위치 도달 기준, 접근 감속은 꺼서 효과 분리.

| planner | 성공 기존→guard | 충돌 기존→guard | timeout 기존→guard |
|---|---:|---:|---:|
| Dijkstra | 24→24 | 0→0 | 0→0 |
| A* | 24→24 | 0→0 | 0→0 |
| Hybrid A* | 15→6 | 9→0 | 0→18 |

18 timeout의 최종 속도는 모두 0. 보수적 정지로 충돌은 줄었지만 도달은 악화.
미사용 지도 검증이나 일반적 안전 보장이 아니다. 샘플 사이 swept collision,
동적 장애물, 센서 오차, 제동 지연은 다루지 않는다.

## 다음 작업

1. 18개 정지 궤적의 위치/clearance/예측 방향/목표 거리로 정지 원인을 분석한다.
2. 측면 장애물에도 멈추는 과보수 제한과 실제 진행 방향 충돌을 구분한다.
3. 안전한 재계획/재출발 구현 후 위치 도달 기준으로 같은 조건에서 비교한다.
4. 성공·충돌·timeout·계획 실패를 모두 보고한다. 정지를 성공으로 세지 않는다.
5. 새 평가에는 새로운 held-out split이 필요하다. 이미 본 평가를 재튜닝하지 않는다.

## 재현 및 파일

analysis/figures는 실행 묶음별 보관. 경로를 이동하지 않아 provenance를 유지했다.
상세 trajectories/clearance 시계열, raw, packages, 수정 전 중간 실행은 ignore된
로컬 자료다. 삭제하지 않는다. Git만으로 이 자료가 복원되지 않는다.
진단 스크립트는 기존 출력 폴더를 덮어쓰지 않는다.
과거 research_all 재개는 소스 hash 변경으로 거부되는 것이 정상이다. 과거
재현은 ZIP 소스로 한다. research_all은 역사적 pose scoring 프로토콜이며
현재 위치 기준의 새 비교에 그대로 사용하지 않는다.

마지막 확인 HEAD는 6bc0b84. 재개 시 사용자의 후속 커밋 여부를 git status/log로
확인한다. 커밋별 파일 안내는 docs/COMMIT_PLAN.md. 정리 중 stage/commit하지 않았다.
