# 이번 변경의 커밋 단위

아직 staging 또는 commit을 수행하지 않았다. 기존 baseline 커밋 e73b245 이후
추가한 분석 기능과 보고 결과를 아래 두 단위로 나눈다.

## 1. feat: 경로 기하 및 실제 주행 clearance 분석 추가

정확한 파일 목록:

- pyproject.toml
- src/raceplan/analyze.py
- src/raceplan/metrics.py
- tests/test_analysis.py
- tests/test_metrics.py

공통 계획 기하, 실제 주행 clearance, 실패 포함 집계, seed 짝비교, 입력 검증과
CLI 등록을 하나의 기능으로 묶는다. 직전 기능 검증은 44 tests passed였다.

## 2. docs: 파일럿 분석 결과와 시각화 보고 정리

문서·렌더러:

- README.md
- docs/RESEARCH_PLAN.md
- docs/GEOMETRY_ANALYSIS.md
- docs/DRIVING_CLEARANCE.md
- docs/COMMIT_PLAN.md
- results/README.md
- results/render_analysis_report.py
- results/render_driving_clearance.py

대표 이미지:

- results/figures/geometry_report.png
- results/figures/driving_clearance_report.png

분석 데이터는 아래 **네 폴더 각각의 episodes.csv, planners.csv, paired.csv,
analysis.json만** 포함한다(총 16개 파일).

- results/analysis/geometry_20261012/demo_noise/
- results/analysis/geometry_20261012/validation_open_noise/
- results/analysis/driving_clearance_20261013/demo/
- results/analysis/driving_clearance_20261013/open/

## 이번 커밋에서 제외

- results/raw/: 기존 ignore 정책 유지. 원본을 삭제하거나 이동하지 않았다.
- results/analysis/driving_clearance_20261013/*/clearance_samples.csv:
  시점별 상세 데이터. 로컬 보관, 재분석으로 재생성 가능.
- results/pilot_repeatability.py, results/figures/planner_comparison.png:
  이미 추적 중이고 이번에 변경하지 않은 파일.

`git add .`로 전부 stage하지 말고 위 파일을 선택한다. 상세 CSV는 삭제하지
않았으며 새로운 ignore 규칙도 추가하지 않았다.
