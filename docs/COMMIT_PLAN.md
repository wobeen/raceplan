# 커밋 구성 — 2026-10-13

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
