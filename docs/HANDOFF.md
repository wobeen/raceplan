# 작업 인계 — 2026-11-04

## 현재 커밋 원칙과 다음 개발

2026-11-04 사용자 지시: 지금까지 RacePlan 작업을 커밋하고, 이후에는 개발 스텝
하나를 완료·검증할 때마다 해당 변경을 커밋한다. 과거의 사용자 직접 staging/commit
원칙은 이 지시로 대체된다. push는 별도 요청 시 진행한다.
다음 스텝은 실행 명령 통합 → 사용자 플래너 오류 처리·실측 계획시간 → 여러 시나리오
일괄 비교 → 결과 화면 개선 → 설치·문서·보관 기준 마무리 순서다.
각 스텝에서 구현을 마친 뒤 테스트를 묶어서 실행하고 검증 결과를 기록한다.
RacePlan과 무관한 .pptx-build/ 및 output/ 발표 자료는 이번 커밋에서 제외한다.

## 스텝2: 사용자 계획 오류 계속 처리·runner 실측 구현

6.1-sol이 plan 호출/데이터 계약 검증 adapter를 추가했다. custom의 일반 예외/잘못된
결과는 planning_error와 type/message를 모든 seed에 기록하고 다음 planner를 계속한다.
builtin 예외·계약 오류, KeyboardInterrupt/SystemExit는 계획 오류로 바꾸지 않는다.
loader/config 사전 오류도 기존대로 중단한다. 유한 타입/값·상태/경로 일관성만 검증하고
차량 안전성/최적성 판정은 추가하지 않았다. 검증한 path는 tuple snapshot으로 저장한다.

기존 reported planning_time_ms는 유지하고 runner_planning_time_ms로 plan 호출1회의
perf_counter 실측을 별도 기록한다. 로딩/grid copy/결과 검증/주행은 제외하며 같은
plan 시간을 seed에 재사용한다. schema1/experiment_revision2의 additive 변경이며
분석/PNG는 구 batch의 실측 누락을 n/a/null로 처리한다. planning_error는 전체 실패와
별도 오류수에 포함하고 모든 계획 실패 batch도 분석·PNG를 완료한다.
기존 sealed runner/raw/protocol/source hash 기록은 그대로 보존한다. 현재 src는 후속
버전이라 당시 live-source hash 불일치는 정상이다. 이번 회귀·smoke는 구현 완료 뒤
묶어서 실행하며 검증·Astra·커밋 기록은 다음 단계다. 구현 에이전트 staging/commit 없음.

구현 완료 뒤 관련23 passed(6.16s), 전체103 passed(9.98s), workflow smoke18행을
한 묶음으로 실행했다. 정상12행 도달·의도한 planning_error6행 not_run, 충돌/timeout/
통상 계획실패0이다. 모든 planner의 runner 측정은1개씩이고3seed에 동일하게 기록한다.
오류 뒤 MyPlanner3건도 도달했으며 A*와 paired 주행 delta0. workflow/analysis/PNG
모두 complete, seed1 PNG 시각 확인 완료. 출력 `results/raw/workflow_step2_20261104/`.
전체 실패·legacy 컬럼·builtin/control-exception 전파 회귀를 통과했고 기존 sealed
runner/raw/protocol 파일 diff0. git diff --check 통과, Astra 검토·커밋은 다음 단계다.

Astra P2/P3 수정으로 오류 type128자/message4096자 제한과 `planning_error_truncated`
및 접미사를 기록한다. 짧은 개행 원문은 CSV에 보존하고 PNG만 한 줄로 정규화하며,
긴 줄은 이진 탐색으로 폭을 맞춘다. reported seconds→ms도 finite인지 검사한다.
수정 완료 뒤 관련24 passed(4.89s), 전체104 passed(7.14s)를 묶어 실행했다.
개행/NUL·14만자 진단·ms overflow 후에도 정상 planner/분석/PNG를 완료하는 E2E와
폭 측정 호출수 회귀를 통과했다. 이전18행 smoke 보존, 별도 재실행 없음. 최종 승인
기록과 커밋은 주 에이전트가 진행하며 구현 에이전트 staging/commit은 없다.
Astra 최종 승인 완료: 초기18건 smoke는 일반 경로, 수정 후 E2E는 긴/개행 오류와
ms overflow 경계를 검증했다. 관련24/전체104 통과이며 잔여 차단 결함은 없다.
스텝2 완료 후 커밋한다. 다음 스텝은 설정 파일 기반 여러 시나리오 일괄 비교다.

## 스텝1: 비교·분석·PNG 통합 명령 구현

6.1-sol이 `python -m raceplan.workflow`와 `raceplan-workflow` 진입점을 추가했다.
기존 experiment/analyze/custom_report 소스는 보존하고 각 main API를 순서대로 호출한다.
새 output-dir 아래 comparison CSV/manifest, analysis/, comparison.png와 workflow.json을
저장한다. 단계별 pending/running/complete/failed 및 failed_phase를 기록하고 실패 후
후속 단계는 실행하지 않는다. 부분 결과는 보존하며 같은 폴더는 재실행하지 않는다.
scenario/planners/custom/seeds/noise/inflation을 전달하고 baseline/report-seed/spacing을
지원한다. 입력/기존 출력/예약 --output/seed/수치 오류는 가능한 실행 전에 거부한다.
사용자 baseline은 plugin import 중복을 피하려고 완료 manifest에서 검증한다.
구현 중 테스트0회, 구현 완료 후 관련9 passed(2.41s), 전체96 passed(5.51s),
workflow smoke1회(4planner×3seed12건)를 묶어 실행했다. 전부 도달했고 충돌/timeout/
계획실패0. 단계3개 모두 complete이며 report seed1 PNG를 시각 확인했다.
출력은 `results/raw/workflow_step1_20261104/`에 보존한다. 통합 테스트는 custom
import1회, 옵션 전달, 기존 출력/예약 인자/seed 거부, experiment·analysis·report
실패 시 상태·부분 결과 보존을 확인했다. 콘솔 진입점은 pyproject에 등록했고 이번
smoke는 `python -m raceplan.workflow`로 실행했다. Astra 독립 검토·커밋은 다음 단계다.
기존 세 모듈 diff0, git diff --check 통과. 구현 에이전트는 stage/commit하지 않았다.

Astra P3로 대시로 시작하는 합법적인 custom 이름/파일의 내부 argparse 전달을
보완했다. baseline/custom은 --option=value로 전달하고 scenario는 절대경로로 전달한다.
`--foo.py:UserPlanner`, `--baseline=--mine`, `-- -demo.yaml`을 함께 실행하는 통합
경계 회귀1개를 추가했다. 수정 완료 뒤 묶어서 관련10 passed(2.24s), 전체97 passed
(4.53s)를 확인했다. 이전 smoke와 출력은 보존했고 새 smoke는 재실행하지 않았다.
Astra 최종 승인 완료. 수정 전 기본 경로는 12건 smoke로, 최종 옵션 전달 수정은
실제 시나리오·플러그인·baseline을 함께 실행하는 E2E 회귀로 검증했다.
관련10/전체97 통과, 기존 세 모듈 변경0을 확인했고 잔여 차단 결함은 없다.
스텝1을 완료했으며 다음 개발 스텝은 사용자 플래너 오류 처리·실측 계획시간이다.

## 최신: 기본 기능 안내와 연구 기능 정리

사용자 요청으로 기본 사용 흐름을 비교 실행 → 저장 결과 분석 → PNG로 정리했다.
README 두 언어판과 results 안내의 중복·오래된 상태·실험별 실행 명령을 줄이고
이전 전문은 docs/archive/에 보관했다. 상세 판단은 docs/FEATURE_SCOPE.md 참고.
Clearance/방향-state 후보와 버전별 guard/recovery는 연구 보관으로 분류했다.
신규 후보의 자동 구현·평가를 다음 기본 작업으로 이어가지 않는다.
실행 코드와 봉인된 산출물은 변경하지 않았고 테스트 재실행 없이 문서 diff를 확인했다.
아래 기록은 이전 개발·평가 이력이다. staging/commit 없음.

## 최신: 신규 split 단일 실행·숫자형 identity 교정·Astra 검증 완료

Astra P2로 v1 query hash가 설계 yaw 정수0과 재로딩 실수0.0을 구분하는 결함을
확인했다. 원래 runner/raw/protocol/seal/사전 snapshot은 그대로 보존하고 별도
`results/turn_aware_query_identity_v2.py`에 숫자 정규화와 저장 scenario round-trip
검증을 구현했다. 교정 기록은
`results/analysis/turn_aware_holdout_20261103_correction_v2/`에 저장했다.
구현 후 관련15 passed(1.34s), 전체91 passed(3.88s), 읽기 전용 감사1회 완료.
source41/input22/artifact120 hash 일치, 기존8개 query의 v1 stored/design은 일치하나
round-trip8개 불일치. v2 canonical design/round-trip은8개 모두 일치했고 지도·좌표와
실행 manifest도 동등했다. v1 source seal과 실행 결과는 바꾸지 않았으며 evaluation
planner/simulation 재실행0회다. 의미상 query fingerprint의 사후 정정이고 기존
봉인을 대체하지 않는다. 지도 신규성·주행 수치 결론은 유지된다.

6.1-sol이 `results/turn_aware_holdout.py`와 사전 프로토콜
`docs/TURN_AWARE_HOLDOUT.md`를 구현했다. 신규10.4×7.2m/0.2m 지도4개와8query,
2family×2split×2query×3seed×5planner 120건을 결과 확인 전 봉인했다. 과거 source16query,
map fingerprint52항목(원본 생성16+저장 YAML36, 중복 포함)과 대조해 exact 중복0.
source41/input22 hash를 각 query 전후 검사했다.
후보0.20은 변경하지 않았고 validation 후 evaluation 각1회, 재튜닝/재실행0회다.

구현 중 테스트/실험0회, 코드 완료 후 관련12 passed(1.53s), 전체88 passed(2.95s),
단일 실행120건을 묶어 완료했다. Validation 도달/충돌: Dijkstra0/12, A*6/6,
Hybrid8/4, 후보0/12, weight0 6/6. Evaluation: Dijkstra0/12, A*0/12,
Hybrid6/6, 후보3/9, weight0 0/12. 각 planner 분모12이며 두 split 모두 timeout/계획실패0.
후보 A* 대비 validation6패·evaluation3승이나 양쪽 동시 도달pair0이므로 RMSE/시간delta 없음.
평가 승리3건은 offset_islands/q0의 세 seed에 한정. 일반 개선으로 승격하지 않는다.

원본 `results/raw/turn_aware_holdout_20261103/`의seal/complete에protocol과
산출물120개 hash 보존. 공유용 표/paired/worst/지도/query는
`results/analysis/turn_aware_holdout_20261103/`, PNG8장
`results/figures/turn_aware_holdout_20261103/`. 대표2장 시각검토 완료. planning4회씩/split,
후보 evaluation median/P95 18.051/22.171ms(A*3.359/4.070), 전체 wall5.758s.
이미 노출한 evaluation은 차기 후보의 미사용 평가로 재사용하지 않는다. Astra는
원본120건과 v2 교정을 독립 재계산해 source41/input22/artifact120 봉인, canonical
query8개 고유성, 실제 입력·manifest 일치를 확인하고 최종 승인했다.
기존 변경/산출물 보존, stage/commit 없음.

## 최신 후속: 방향-state 사용자 후보 구현·Astra 독립 검증 완료

계속 진행 요청에 따라 6.1-sol이 `examples/turn_aware_planner.py`에 비위임 A*를
구현했다. `(cell,incoming_direction)` 상태와 길이+방향변화0.20m/rad 비용이며,
가중치0 ablation도 제공한다. 값은 실행 전 고정했고 기존 MyPlanner 예제는 보존했다.
목표 yaw/차량 운동학/footprint를 탐색에서 보장하지 않는 점-grid 후보이며,
기존 clearance 후보의 반복 튜닝은 아니다. `docs/TURN_AWARE_CANDIDATE.md` 참고.

구현 중 테스트/실험0회. 구현 후 관련8 passed(2.73s), 전체84 passed(3.74s),
`results/turn_aware_comparison.py`의 demo 무잡음/고정잡음2조건×5planner×3seed30건을
한 묶음으로 실행해30/30 도달·충돌/timeout/계획실패0을 확인했다. PNG2장 시각검토와
기존 analyze 완료. 사전 protocol·설계 사본과 산출물 hash를 저장했다.
후보는 A*와 같은11.07107m 길이에서 회전합4.71239→2.35619rad, 고정잡음 중앙값
RMSE0.12881→0.08030m지만 완료시간12.85→13.20s, 실제 최소 clearance0.28295→
0.26693m로 trade-off다. 최대 이산 곡률은 더 크다. weight0은 이번 두 조건의
paired 주행 delta0. 이미 사용한 demo의 개발 결과라 held-out 개선 근거가 아니다.

원본 `results/raw/turn_aware_20261103/`, 공유용 요약/설계/hash 복사본
`results/analysis/turn_aware_20261103/`, 이미지
`results/figures/turn_aware_20261103/{clean,noise}.png`. 기존 결과·PPTX/사용자 변경을
보존했고 stage/commit하지 않았다. Astra는 랜덤 소형 격자100개의 양의 가중치와
가중치0 총200건을 독립 Dijkstra oracle과 대조해 비용·상태 불일치0을 확인했다.
두 batch의 소스·원본·공유 산출물 hash, 30개 주행, weight0/A* 전체 시계열과
문서 수치도 일치해 차단 결함 없이 최종 승인했다.

## 최신: 사용자 플래너 비교 구현·Astra 독립 검증 완료

재개 HEAD `112c3dc`(인계 이후 README 변경 커밋 2개). 기존 미커밋 사용자 플래너
연결/리포트 초안을 이어서 6.1-sol이 구현했다. `--custom-planner FILE.py:CLASS`로
기본 세 planner와 동일 지도/query/차량/controller/seed에서 비교한다. 파일 bytes와
hash가 일치하도록 로드하고 planner별 지도 사본으로 입력 변경을 격리한다.
기존 CSV 컬럼·기본 회복 v2 및 frozen 실험은 유지한다.

`raceplan.custom_report`는 완료된 batch와 지도 hash를 확인하고 저장 query를 사용해
전체 seed 성공·충돌·timeout·계획실패 수와 선택 seed의 경로/궤적을 PNG로 만든다.
legacy `path_cost_m`의 planner 정의 비용과 XY 경로 길이를 구분한다.
구현 중 테스트0회, 구현 후 전체 pytest1회 **79 passed (4.72s)**.
첫 standalone smoke는 `.venv`에 프로젝트 미설치로 모듈 탐색 단계 종료(산출물0).
프로세스 `PYTHONPATH=src` 설정 후 demo 4 planner×3 seed **12건 전부 도달**, 충돌/
timeout/계획실패0. A* 위임 MyPlanner의 paired 지표는 A*와 동일하며 개선 주장이 아니다.
무잡음 반복이므로 독립 성능 표본이 아니다. PNG·기존 analyze 실행 및 이미지 검토 완료.

출력 `results/raw/custom_planner_20261103*`,
`results/figures/custom_planner_20261103.png`,
`results/analysis/custom_planner_20261103/`. 상세 인터페이스·범위·검증·후속 계획은
`docs/CUSTOM_PLANNER_COMPARISON.md` 참고.

Astra 1차 검토의 P2(config 유실·JSON 직렬화 실패)를 수정했다. JSON 호환
mapping/dataclass/중첩 설정은 snapshot으로 보존하고 Path·ndarray 등의 미지원 값은
플래너 이름·설정 위치를 표시하며 결과 디렉터리/파일 생성 전에 거부한다. manifest의
전체 직렬화도 파일을 열기 전에 끝낸다. 계획시간은 planner 자체 보고값임을 PNG/
manifest/문서에 명시하고, clearance delta는 양쪽 주행만 있으면 계산되는 예외를
문서에 반영했다. 수정 코드 완료 뒤 묶어서 **관련8 passed (1.33s), 전체80 passed
(2.53s)**. 최종 소스로 새 smoke12건 모두 도달·충돌/timeout/계획실패0, PNG와
analyze도 성공했다. 최종 출력은 `results/raw/custom_planner_20261103_reviewed*`,
`results/figures/custom_planner_20261103_reviewed.png`,
`results/analysis/custom_planner_20261103_reviewed/`이며 이전 출력도 보존했다.
Astra는 최종 소스·지도·시나리오·분석 입력·예제 SHA-256 47개를 reviewed 출력과
대조해 불일치0을 확인했다. 12/12가 목표거리0.5m 이내·충돌0이며 A*와 MyPlanner의
저장 경로 및 seed별 258개 전체 궤적 sample이 일치한다. PNG 구조/크기와 P2 수정도
재검토해 차단 사항 없이 최종 승인했다.

기존 미커밋 변경과 `.pptx-build/`, `output/` 등 산출물 보존, stage/commit 없음.
아래 2026-10-14 이전 회복 기록은 historical 결과이며 새 평가와 합치지 않는다.

## 현재 후속 작업: 회복 v4 코드 완료, Astra 검증 대기

기본v2/비교v3 보존. v4는 exact request-local clearance cache 및 비음수 비용 하한
선검사, 전체 tail4000 nodes/3*planning_timeout(기본9s) 공유예산으로 비용을 제한한다.
후보순서/clearance/preview는 동일하며 비용 개선이 도달 개선을 보장하지 않는다.
저장 v3 실패5건은 안전prefix 없음1건, 생성후preview 거부2건, tailtimeout만2건이다.
문서 RECOVERY 마지막 절에 근거/한계/명령을 기록했다. --compare-v4는 Hybrid48건.
구현 중 테스트/실험0회이며 stage/commit/기존결과 변경삭제없음.
아래 v3 완료 기록과 과거 전체테스트는 historical 기록이다.

## 현재 후속 작업: 회복 v3 구현 및 Astra 검증 완료

확인 HEAD `8c5f8cb`. 회복 v3는 v2 preview 거부 뒤 현재 정지 pose에서
전진 arc+clearance/조향 비용 Hybrid tail 후보를 최대15개 탐색한다.
`--compare-v3`는 Hybrid만 동일 저장 첫 경로·seeds로 v2/v3 48건을 비교한다.
기본 회복은 계속 v2이며 v1/v2 및 기본 Hybrid 비용은 유지한다.
구현 후 targeted 테스트 1회 **33 passed**, Hybrid v2/v3 비교 1회 **48건** 완료.
v2 15/24 성공·9회복실패 → v3 **19/24 성공·5회복실패**, 두 조건 충돌/timeout/계획실패0.
수락 대안4개가 모두 실제 도달했고 기존 성공15건 회귀0·평균11.8467초 동일하다.
대안125개 중 prefix 여유 거부103, tail timeout15, 경로생성7(수락4/preview 거부3).
추가 대안 계산64.263초, 전체 재계획65.109초(v2 .817초), preview1.566초(v2 .104초).
planning wall time은 주행시간에 포함되지 않으며 현재 구현은 실시간성 검증이 아니다.
기존 v2 Hybrid24건 종료지표·전체 sample 일치, 입력/소스/산출물 hash 불일치0.
PNG 두 장 시각검토 완료. 출력 `results/analysis/recovery_v3_20261013/` 보존.
2026-10-14에는 기존 산출물 검토·문서화만 마무리했고 테스트/실험을 재실행하지 않았다.
사용자 범위에 따라 전체 pytest/Dijkstra/A* 비교 및 반복 튜닝은 실행하지 않았다.
아래 과거 전체 테스트 기록은 historical 결과이며 이번 허가 범위가 아니다.
최신 설계·명령은 RECOVERY 문서 마지막 절 참고. stage/commit 없음.

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

마지막 확인 HEAD는 8c5f8cb. 재개 시 사용자의 후속 커밋 여부를 git status/log로
확인한다. 커밋별 파일 안내는 docs/COMMIT_PLAN.md. 정리 중 stage/commit하지 않았다.

## 2026-10-14 v4 검증 완료 (최신)

Astra 정적검토 후 지정 관련 테스트1회36 passed, Hybrid v3/v4 비교1회48건 완료.
현재 v3/v4 모두22/24 도달·충돌0·회복실패2이며 모든24쌍 sample이 정확히 동일하다.
계획+preview 23.5501→13.5881초(42.3% 감소), 같은 성공22쌍 완료시간13.0091초 동일.
과거 v3의19/24와 이번 v3 자체22/24는 wall timeout 의존 탐색의 historical 차이이며
v4 성공 개선으로 귀속하지 않는다(samples7건/종료3건 차이). 신규 실패/성공회귀0.
남은 slalom q1 seed0은 tail3개 preview 거부, seed1은 prefix15개 전부 거부다.
request 예산 실제 소진0이므로 소진시 성공 손실 위험과 hard deadline 보장은 미검증.
출력 `results/analysis/recovery_v4_20261014/`; verification.json, 두 PNG 검토 완료.
상세 결과/한계는 RECOVERY_20261013.md 마지막 절. 전체 pytest·다른 planner·반복
튜닝 없이 종료했으며 과거 출력/미커밋 변경 보존, stage/commit하지 않았다.
