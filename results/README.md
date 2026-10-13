# 결과 폴더

CSV는 분석 종류 → 실행 날짜 → 지도 단위로 묶는다. 같은 batch의 episode,
planner 집계, seed 짝비교와 provenance JSON은 함께 보관한다.

```text
results/
  raw/                              # 기존 원본 실험, Git 제외
    pilot_20261012/                  # summary / paths / trajectory / manifest
  analysis/
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
