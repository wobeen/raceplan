# 작업 인계 — 2026-10-13

2026-10-13 후속 v2 구현 및 Astra 검증 완료. 전체 pytest 1회 **71 passed**,
v1/v2 비교 1회 **144건** 실행. 기존 v1 72건 모든 sample·종료 결과를 정확히 재현했다.
세 개선은 후보 prefix 실행 검사/동일 막힌 경로 거부, creep 정상속도 복귀 hysteresis,
경로 진행도+순변위 watchdog이다. v1·v2 각각 63/72 성공, 충돌0·회복실패9로 동일하다.
Hybrid 같은 성공15건 시간은 15.74→11.85초(24.7% 단축), 재계획27→9회다.
v2의 후보9개는 모두 거부되어 재계획으로 도달을 복구한 증거는 없다.
출력 `results/analysis/recovery_v2_20261013/`, 네 PNG 시각검토·hash/재현 대조 완료.
`docs/RECOVERY_20261013.md` 마지막 절에 상세 결과·한계·다음 설계 의견을 기록했다.
기존 출력 보존, 반복 튜닝·stage·commit 없음.

## 사용자 확정 사항

- 한국어로 보고. 이번 회복 구현은 전체 코드 작성 후 테스트/실험을 일괄 실행하고 결과 이미지와 분석을 제공한다. 구현은 6.1, 검증·설계 의견은 Astra 담당.
- 테스트는 추가 승인 없이 진행. 커밋과 staging은 사용자가 직접 한다.
- 성공은 충돌 없이 목표 위치 0.5m 이내 진입. yaw는 참고값이다.
- 기존 변경 및 frozen 원본은 보존한다. 이전 방향 필수 실험과 현재 기준을 혼합하지 않는다.

## 환경과 현재 상태

Windows PowerShell, `C:/Users/sinub/OneDrive/Desktop/raceplan`.
실행 `.venv/Scripts/python.exe`, 테스트 `-m pytest -q`: 최신 회복 v2 구현 후 71 passed.
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

사용자 요청으로 테스트 수를 73→65개로 축소했다(65 passed).
설정값 오류의 반복 입력 7건과 CLI 테스트에 중복되는 demo 비교 1건을 제거했다.
충돌/도달/제어/재현성 검증은 유지. 앞으로 단순 설정 추가마다 테스트를 늘리지 않는다.

2026-10-13 후속: 정지 원인 분석 완료. `docs/GUARD_STOP_20261013.md` 참고.
18건 모두 최종 측면 속도 상한 0이며, 그중 9건은 전방 고정 조향 예측 충돌도 있음.
제어 동작은 유지하고 진단 함수와 분석 스크립트를 추가. 전체 73 tests passed.
다음은 재출발/재계획 정책 구현과 동일 조건 비교. 아래 1~2의 최종 상태 진단은 완료.

1. 18개 정지 궤적의 위치/clearance/예측 방향/목표 거리로 정지 원인을 분석한다.
2. 측면 장애물에도 멈추는 과보수 제한과 실제 진행 방향 충돌을 구분한다.
3. 안전한 재계획/재출발 구현 후 위치 도달 기준으로 같은 조건에서 비교한다.
4. 성공·충돌·timeout·계획 실패를 모두 보고한다. 정지를 성공으로 세지 않는다.
5. 새 평가에는 새로운 held-out split이 필요하다. 이미 본 평가를 재튜닝하지 않는다.

## 재현 및 파일

2026-10-13 회복 구현 코드 추가: `docs/RECOVERY_20261013.md` 참고. optional
`RecoveryConfig`와 fully-stopped current-pose replanner callback, 저속 전방 재출발,
목표거리 진전 watchdog 및 총 횟수 제한, `planning_failed`/`recovery_failed`를 추가했다.
`results/recovery_comparison.py`는 frozen guard manifest/paths를 읽어 동일 조건
baseline/guard/recovery 및 지표/PNG를 생성한다. 기존 출력은 덮어쓰지 않는다.
구현 중에는 테스트/실험을 실행하지 않았다. 구현 후 Astra 정적 검토와 전체 pytest
1회(68 passed), 비교 runner 1회(216건)를 완료했다. 출력은
`results/analysis/recovery_20261013/`. 기존 baseline/guard 144건 모든 궤적 sample과
종료 결과가 과거 출력과 정확히 일치하고 입력·산출물 hash를 확인했다.
Dijkstra/A*는 각 조건 24/24 성공. Hybrid는 기존15성공9충돌 → guard6성공18timeout
→ 회복15성공9회복실패(충돌/timeout/계획실패0). 저속 재출발이 9건을 복구했고,
실패9건은 재계획27회가 모두 planner success여도 도달하지 못해 횟수 제한으로 종료했다.
성공15건 평균 시간은 기존7.51초→회복15.74초로 악화. 재계획의 실제 회복 성공 증거는
없다. 네 결과 PNG 시각검토 완료. 상세 한계/차기 설계 판단은 RECOVERY 문서에 있다.
이는 validation 재사용 진단이며 정책 재튜닝이나 새 held-out 평가를 하지 않았다.

analysis/figures는 실행 묶음별 보관. 경로를 이동하지 않아 provenance를 유지했다.
상세 trajectories/clearance 시계열, raw, packages, 수정 전 중간 실행은 ignore된
로컬 자료다. 삭제하지 않는다. Git만으로 이 자료가 복원되지 않는다.
진단 스크립트는 기존 출력 폴더를 덮어쓰지 않는다.
과거 research_all 재개는 소스 hash 변경으로 거부되는 것이 정상이다. 과거
재현은 ZIP 소스로 한다. research_all은 역사적 pose scoring 프로토콜이며
현재 위치 기준의 새 비교에 그대로 사용하지 않는다.

마지막 확인 HEAD는 6bc0b84. 재개 시 사용자의 후속 커밋 여부를 git status/log로
확인한다. 커밋별 파일 안내는 docs/COMMIT_PLAN.md. 정리 중 stage/commit하지 않았다.
