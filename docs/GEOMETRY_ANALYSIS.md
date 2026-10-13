# 지도·경로 지표와 저장 결과 분석

2026-10-13 후속 확장: 실제 주행 clearance 및 실패 포함 집계, 44 tests passed.
정의·새 결과는 [DRIVING_CLEARANCE.md](DRIVING_CLEARANCE.md) 참조.
현재 분석 명령은 trajectory CSV도 읽으며 analysis schema 2를 출력한다.

상태: 2026-10-12 사용자 승인 후 42 tests passed, 기존 잡음 파일럿 18 episode 분석 및 이미지 보고 완료.

## 범위

기존 summary와 같은 이름의 manifest, paths CSV를 읽는다. planner와 simulator를
호출하지 않는다. raw map과 inflated map의 장애물 셀 비율을 따로 기록하며,
clearance는 batch와 같은 inflated map을 사용한다. 지도 YAML·image hash가
기존 manifest와 다르면 중단한다. 서로 다른 batch를 자동으로 합치지 않는다.

```powershell
.venv/Scripts/python.exe -m raceplan.analyze results/raw/pilot_20261012/demo_noise.csv --output-dir results/analysis/geometry_20261012/demo_noise
```

새 설치/동기화 후에는 `raceplan-analyze` entry point도 사용할 수 있다.

## 지표 정의

- path_length_m: 원본 XY polyline 길이. planner cost와 구분한다.
- path_to_query_distance_ratio: 위 길이 / scenario 시작·목표 직선거리.
  planner별 goal tolerance와 endpoint 차이로 1 미만일 수 있어 최적성 비율로 해석하지 않는다.
  시작·목표 offset과 goal yaw error를 함께 기록한다. 동일 시작·목표면 비율은 비운다.
- 곡률: 공통 arc-length 간격으로 resample한 XY segment heading 차이 / 간격.
  간격 기본값은 0.1 m이며 length/ceil(length/requested_spacing)으로 균등하게 맞춘다.
  미분 가능한 곡선의 실제 곡률이 아니라 spacing에 의존하는 이산 근사이다.
  점 하나 또는 segment 하나라 곡률을 추정할 수 없으면 빈 값이다.
- footprint clearance: resample pose와 원본 waypoint에서 회전된 차량 사각형과
  occupied cell 사각형/지도 경계 사이의 최소 유클리드 거리. 교차·접촉은 0이다.
  yaw는 원본 pose를 최단 각도로 보간한다. grid 경로의 yaw는 실행 차량 yaw와
  다를 수 있으므로 이는 계획 pose에 놓인 footprint 기준이다.
- sampled clearance는 연속 swept clearance의 보장이 아니다. 큰 간격은 중간
  충돌을 놓칠 수 있다. 중복 위치의 yaw-only 변화는 균등 resample에서 생략하지만
  원본 pose도 clearance 검사에 포함한다.
- local_clearance_diameter_proxy: reference point 최소 clearance × 2 / 차량 폭.
  경로 의존 근사치이며 지도 병목 폭이나 planner 독립 난이도가 아니다.
- obstacle density는 지도 전체 셀(테두리 포함) 기준이다. 해상도·crop·inflation이
  다르면 같은 난이도로 단정할 수 없다.

## 저장과 해석

- episodes.csv: 실패를 포함한 원본 episode에 경로·지도 지표, 실패 분류,
  차량 폭으로 나눈 RMSE를 추가한다. 계획이 없으면 경로 지표는 비운다.
- planners.csv: 전체 episode 분모의 도달률, 계획 실패/초기 충돌/주행 충돌/
  timeout 수와 도달 episode만의 RMSE·시간·조향 포화 중앙값, Q25/Q75/Q90.
- paired.csv: 동일 seed의 planner와 baseline 결과, 둘 다 도달했을 때만 연속
  지표의 차이(planner − baseline). baseline 기본값은 dijkstra이다.
  baseline 하나만 입력한 batch에는 paired.csv가 생성되지 않는다.
- analysis.json: 입력·분석 소스 hash, 지표 정의·간격·baseline과 NumPy 버전.

불완전 batch, 중복 episode/planner-seed, 누락 seed 조합은 거부한다. 결과 폴더가
이미 있으면 중단한다. 실패 episode를 성공 episode 통계에 섞거나 제외된 실패를
숨기지 않도록 실패 개수와 연속 지표의 집단을 명시한다.

잡음 seed 반복은 독립 지도 표본이 아니다. 지도별 유의성·일반화 또는 인과적
관계는 이 단일 batch 집계로 주장하지 않는다. 여러 batch의 통합, CI/효과크기,
그래프, 정확한 병목 추출과 planner 선택 규칙은 후속 범위다.

현재 clearance 계산은 sample 수 × occupied cell 수에 비례하는 순차 구현이다.
소형 지도 분석이 대상이며 대형 지도에는 spatial indexing 최적화가 필요할 수 있다.

## 실행한 검증

1. 기존 회귀 테스트와 신규 기하·분석 핵심 테스트 실행.
2. 직선·직각 경로 길이/곡률, 경계·장애물 clearance 기대값 확인.
3. 저장 batch의 paired 집계 및 seed 누락 거부 확인.
4. 기존 두 지도 파일럿 CSV에 분석 명령 적용, 값·실패 분류·파일 연결 확인.

이번 검증에는 새 주행 실험이 필요하지 않다.


## 관찰 결과

- Demo RMSE 중앙값: Dijkstra 0.08587 m, A* 0.12803 m, Hybrid A* 0.02485 m.
- Open RMSE 중앙값: Dijkstra/A* 0.00335 m, Hybrid A* 0.01433 m.
- Demo Hybrid A*의 계획 footprint 최소 표본 clearance는 0.05299 m로,
  Dijkstra/A*의 0.11000 m보다 작다. 추종 오차와 장애물 여유 공간은 별도 지표다.
- Demo Hybrid A*의 계획 끝점은 목표에서 0.46135 m 떨어져 있다. 길이가 짧다는
  사실을 동일 endpoint 경로의 최적성으로 해석하면 안 된다.
- 전체 18 episode는 도달했고 실패가 없다. 새 주행을 실행한 결과가 아니라
  앞서 저장한 noise batch의 재분석이다.
- 원본/팽창 obstacle density는 이번 inflation=0 조건에서 같다. Demo 41.67%,
  Open 46.67%로, 작은 지도의 테두리 비율 탓에 Open이 더 높다. 밀도 하나만으로
  지도 난이도를 정렬하는 것은 적절하지 않다.

이미지: `results/figures/geometry_report.png`.

```powershell
.venv/Scripts/python.exe results/render_analysis_report.py
```

렌더러는 두 noise batch의 분석 CSV와 demo의 계획·주행 CSV를 읽어 PNG로 그린다.
42개 테스트 결과는 해당 검증 시점의 보고 문구이며 렌더러가 테스트를 다시 실행하지 않는다.
