# 결과 폴더

## 현재 결과와 보관 기준

현재 실행 파일은 `obstacle_guard_diagnostic.py`이고, 위치만 도달 기준으로 쓴다.
`analysis/obstacle_guard_20261013/`에 설정/경로/episode/집계를 보관하며 그림은
`figures/obstacle_guard_20261013.png`다.

| 실행 묶음 | 목적 |
|---|---|
| goal_termination_20261013 | 과거 위치 종료 vs 방향 필수 종료 비교 |
| approach_speed_20261013 | 과거 방향 필수 조건에서 접근 감속 비교 |
| obstacle_guard_20261013 | 현재 위치 기준 장애물 감속·정지 비교 |
| research_20261013 | 당시 pose 기준의 frozen 연구 사이클 |

스크립트 경로와 provenance를 보존하기 위해 기존 실험 묶음은 이동하지 않는다.
코드·문서·그림·episode/요약·경로·설정은 Git에 포함한다. 상세
`trajectories.json`, `clearance_samples.csv`, 수정 전 중간 실행, `raw/`,
`packages/`는 ignore하고 로컬에 유지한다. Git만으로 상세 자료는 복원되지 않는다.
새 진단은 같은 출력 폴더가 있으면 실패하며, 과거 연구 재개는 소스 hash도 검사한다.


전체 연구 사이클:

- `raw/research_20261013/`: sensitivity / validation / tune / evaluation 단위별 원본
- `analysis/research_20261013/`: 단계별 CSV, 집계, 짝비교, freeze/seal, hash 검증
- `figures/research_20261013/`: sensitivity / validation / evaluation / failures PNG
- `packages/research_20261013.zip`: 소스·원본 데이터·보고서와 checksum을 묶은 재현 ZIP

`research_all.py`가 전체 단계를 순서대로 실행·재개한다.

CSV는 분석 종류 → 실행 날짜 → 지도 단위로 묶는다. 같은 batch의 episode,
planner 집계, seed 짝비교와 provenance JSON은 함께 보관한다.

```text
results/
  raw/                              # 기존 원본 실험, Git 제외
    pilot_20261012/                  # summary / paths / trajectory / manifest
  analysis/
    corridor_width_20261013/         # 통로 폭 5단계, batch별 CSV와 통합표
    geometry_20261012/               # 초기 계획 경로 기하 분석
      demo_noise/
      validation_open_noise/
    driving_clearance_20261013/      # 실제 주행 clearance 확장 분석
      demo/
      open/
  figures/                          # 보고 이미지
    planner_comparison.png
    geometry_report.png
    driving_clearance_report.png
    corridor_width_report.png
  pilot_repeatability.py
  render_analysis_report.py
  render_driving_clearance.py
```

각 분석 지도 폴더:

| 파일 | 용도 |
|---|---|
| episodes.csv | episode별 계획·주행 지표 |
| planners.csv | planner별 집계 |
| paired.csv | 같은 seed의 baseline 대비 차이 |
| clearance_samples.csv | 주행 시점별 clearance, 확장 분석에만 존재 |
| analysis.json | 분석 설정·입력 hash·소스 hash |

원본 batch는 loader가 summary와 나란히 있는 paths/trajectory/manifest를
찾으므로 기존 배치를 유지한다. 파일 종류만으로 전체 CSV를 한 폴더에 합치지 않는다.
기존 analysis.json은 당시 provenance를 보존하며 이동 때문에 hash를 다시 쓰지 않는다.

커밋에는 대표 그림, 요약 CSV와 analysis.json을 권장한다. raw와
clearance_samples.csv는 로컬에 보관하고 별도 데이터 보관 대상으로 둔다.
이미지 재생성에는 이 로컬 상세 데이터가 필요하며, 코드 커밋만으로 raw가 복원되지는 않는다.
