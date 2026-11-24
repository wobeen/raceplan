# 커밋 구성 — 2026-10-13

## 2026-11-24 연구 스텝 절차 (현재 적용, 정책 v2 시험 브랜치)

후보 개발·평가처럼 결과로 판단하는 연구 스텝은 아래 순서를 따른다. 기능 스텝의
"스텝마다 구현·검증·문서화 후 커밋" 원칙은 그대로이며 이 절이 연구 스텝에 덧붙는다.

1. **착수 승인**: 사용자가 해당 연구 스텝을 명시적으로 요청·승인한 경우에만 시작하고,
   HANDOFF 기록에 요청 문구와 날짜를 남긴다. 이전 스텝의 "다음 후보" 제안은 승인이 아니다.
2. **사전 등록 커밋**: 프로토콜 문서, 후보 코드, runner, 테스트를 결과 없이 먼저 커밋한다.
   이 커밋 전에는 판단 대상 데이터에서 주행을 실행하지 않는다.
3. **독립 검토**: 사전 등록 커밋을 다른 모델(예: `anthropic/claude-fable-5-2`,
   `openai-codex/gpt-6.2-astra`)이 읽기 전용으로 검토한다. 모델명·지적·반영 여부를
   프로토콜 문서에 기록하고, 반영으로 코드가 바뀌면 다시 커밋한 뒤 실행한다.
4. **실행**: 추적 파일이 깨끗한 상태에서 runner를 한 번 실행한다. runner는 실행 커밋과
   dirty 여부를 기록하며 dirty면 실행을 거부한다.
5. **결과 커밋**: 공유 산출물을 `results/analysis/`에 복사한 **뒤** 전체 pytest를 다시 실행하고,
   결과·문서를 별도 커밋으로 남긴다. 결과를 본 뒤의 코드 변경은 새 스텝이다.

커밋 메시지는 한국어로 쓰고 끝에 `Co-Authored-By` 트레일러를 붙인다. push는 요청 시에만 한다.

## 2026-11-04 사용자 지시 (현재 적용)

이전의 사용자 직접 staging/commit 원칙을 대체한다. 현재까지 RacePlan 변경은
checkpoint로 커밋하고 이후 개발은 아래 스텝마다 구현·검증·문서화를 마친 뒤 커밋한다.
push는 별도 요청 시 진행한다. 관련 없는 사용자 파일은 커밋에 포함하지 않는다.

1. 비교 실행·분석·PNG 명령 통합
2. 사용자 플래너 오류 처리와 실행기의 실제 계획시간 측정
3. 설정 파일 기반 여러 시나리오 일괄 비교·집계
4. 결과 비교표와 대표 성공·실패 궤적 개선
5. 새 환경 설치 검증·최소 사용 문서·데이터 보관 기준 마무리

각 스텝의 테스트는 코드 작성 완료 후 묶어서 실행한다. 아래는 과거 커밋 안내다.

### 스텝1 — 비교 실행·분석·PNG 통합

`src/raceplan/workflow.py`, 진입점 pyproject, workflow 회귀 테스트와 한/영 README를
한 단위로 묶는다. 기존 experiment/analyze/custom_report는 변경하지 않는다.
새 폴더·단계별 상태·부분 결과 보존, custom import1회 및 기존 옵션 전달을 검증한다.
구현 에이전트가 코드 작성 후 관련/전체 pytest와 smoke를 묶어 실행하고, Astra 독립
검증 후 주 에이전트가 해당 스텝을 커밋한다. .pptx-build/output 사용자 자료는 제외한다.
구현 후 관련9 passed(2.41s), 전체96 passed(5.51s), workflow smoke12건 모두 도달.
출력 `results/raw/workflow_step1_20261104/`, PNG 시각 확인과 diff --check 완료.
구현 에이전트는 staging/commit하지 않았고 Astra 독립 검토 대기다.
Astra P3 전달 경계 수정 후 관련10 passed(2.24s), 전체97 passed(4.53s).
기존 실행기/분석기/렌더러는 그대로 보존했다. Astra 최종 승인 완료: 초기 smoke는
기본 경로를, 수정 후 E2E 회귀는 최종 옵션 전달을 검증했다. 스텝1 완료 후 커밋한다.

### 스텝2 — custom 오류와 runner 실측

common 상태/plan adapter, experiment의 별도 실측·오류 필드, analysis/report의 오류
집계와 legacy 호환, 핵심 계약·계속 실행·전체 실패 회귀 및 README/인터페이스를 묶는다.
기존 sealed runner/raw/protocol/hash 기록은 수정하지 않으며 현재 src는 후속 버전이다.
구현 완료 후 관련/전체 pytest와 정상·실패 custom workflow smoke를 묶어서 실행하고
Astra 독립 검증 후 주 에이전트가 커밋한다. 구현 에이전트는 stage/commit하지 않는다.
구현 후 관련23 passed(6.16s), 전체103 passed(9.98s), workflow smoke18행 중 정상12도달/
의도한 planning_error6 not_run. 출력 `results/raw/workflow_step2_20261104/`, PNG 시각
확인과 diff --check 완료. Astra 독립 검토 대기다.
Astra P2/P3 진단 길이·개행 표시·ms finite 수정 후 관련24 passed(4.89s),
전체104 passed(7.14s). 최종 소스는 E2E 회귀로 확인했고 이전 smoke를 보존했다.
Astra 최종 승인 완료. 관련24/전체104 통과, 초기 smoke와 최종 수정 E2E를 구분해
기록했다. 잔여 차단 결함 없이 스텝2를 커밋한다.

### 스텝3 — 설정 파일 기반 suite

새 suite 모듈/진입점, strict 설정·coverage·기본 집계 회귀4개, 예제 YAML과 최소 사용
문서를 묶는다. 기존 실험/분석/리포트/봉인 자료는 보존하고 workflow에는 구조화된
control_exception 플래그만 추가한다. 구현 완료 뒤 관련/전체 pytest와
소규모 demo/open smoke를 묶어 실행하고 Astra 독립 검증 후 주 에이전트가 커밋한다.
구현 에이전트는 staging/commit하지 않는다.
구현 후 관련17 passed(6.72s), 전체108 passed(8.95s), suite smoke16/16도달·missing0.
출력 `results/raw/suite_step3_20261105/`, PNG2장 시각검토·diff --check 완료.
중단 서브클래스 수정 후 첫 관련 묶음은 WinError5로1실패·16통과, 전체 미실행.
동일 코드 재실행에서 관련17 passed(3.95s), 전체108 passed(7.12s). 초기 smoke는
수정 전 결과로 보존하고 최종 필드는 E2E로 검증했다. Astra 최종 승인 완료:
관련17/전체108 통과와 독립 집계를 확인했고 잔여 차단 결함 없이 스텝3을 커밋한다.

### 스텝4 — 저장 결과 HTML·대표 궤적

새 report 모듈/진입점, saved batch, partial suite, 전체 계획 실패, escaping·입력 변조,
파생 paired 변조 회귀 5개와 사용 문서를 묶는다. 기존 실행/렌더 모듈과 원시 결과를
보존하고 새 output-dir에 생성한다. P2 수정 후 관련 15개와 전체 113개 테스트를
통과했다. 저장 정상 suite, 계획 오류 batch, 충돌 holdout batch의 HTML 3건을 새
`_reviewed` 폴더에 생성했다. Astra 최종 승인으로 스텝4 검증을 마쳤다.

### 스텝5 — 새 환경 설치·사용 문서·결과 보관

한·영 README의 Windows 새 환경 설치부터 workflow·suite·HTML까지의 흐름,
`results/README.md`의 Git·공유·백업·봉인 기준과 `results/reports/`의 Git 제외를 묶는다.
Windows CPython 3.13.7에서 캐시만 사용한 uv 잠금 wheel 설치 후 저장소 밖에서
전체 113개 테스트(18.20s)와 설치 콘솔 명령을 한 묶음으로 통과했다. Workflow 9건,
suite 16건이 도달했고 report는 누락 0과 대표 PNG 4장을 기록했다. 출력과 환경은
[HANDOFF](HANDOFF.md)에 기록했다. Astra가 비편집 설치와 실행 결과를 독립 검증해
승인했다. 스텝5 검증을 마쳤다.

## 과거 안내 (현재 커밋 원칙으로 대체됨)

커밋과 staging은 사용자가 수행한다. 이전 분석/보고 커밋은 9758b8f 및
6bc0b84로 반영되었다. 아래는 그 이후 작업의 권장 단위다.

## 1. feat: 연구 실험과 접근 감속·장애물 정지 제어 추가

- src/raceplan/metrics.py, tests/test_metrics.py
- src/raceplan/common/planning_space.py
- src/raceplan/corridor_suite.py, tests/test_corridor_suite.py
- src/raceplan/planners/clearance_astar.py
- src/raceplan/research_*.py, tests/test_research.py
- src/raceplan/controllers/pure_pursuit.py
- src/raceplan/simulator/kinematic.py, src/raceplan/simulator/obstacle_guard.py
- tests/test_goal_termination.py, tests/test_approach_speed.py, tests/test_obstacle_guard.py
- scenarios/corridor_width/
- results/ 아래 새 Python 실험·분석·렌더 스크립트

전체 검증 71 tests passed. 과거 pose scoring은 재현용으로 유지하며
현재 obstacle_guard 진단은 위치 도달 기준이다.

## 2. docs: 결과 정리 및 위치 도달 기준 인계 문서 추가

- .gitignore, README.md, docs/ 내 변경·신규 문서
- results/README.md
- results/figures/ 내 신규 PNG
- results/analysis/ 내 ignore되지 않은 episode/요약/경로/설정/CSV/JSON

공유 파일의 기능 변경이 겹치므로 코드/테스트 전체와 문서/결과로 나눴다.
전체를 한 checkpoint 커밋으로 묶어도 된다.

## 제외하고 로컬 보관

- results/raw/, results/packages/: 원본 및 과거 소스 재현 ZIP
- results/analysis/**/trajectories.json: 전체 시계열
- results/analysis/**/clearance_samples.csv: 상세 clearance
- results/analysis/*_pre_boundary_fix/: 수정 전 중간 실행

모두 삭제하지 않고 ignore 처리했다. 별도 백업 없이 Git만으로 복원되지 않는다.
`git status --short`, `git diff --stat` 확인 후 사용자가 선택적으로 stage/commit한다.
이번 정리에서 Codex는 stage/commit하지 않았다.
