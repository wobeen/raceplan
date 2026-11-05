# 저장 결과 HTML 리포트

완료된 workflow/batch 또는 suite 폴더를 읽어 새 폴더에 정적 HTML과 대표 PNG를 만든다.
설치 후 `raceplan-report`도 같은 인자를 받는다. 기존 selected-seed `custom_report` 명령은
그대로 사용할 수 있고 HTML 리포트는 별도 명령으로 생성한다.

```powershell
python -m raceplan.report results/raw/my_suite --output-dir results/reports/my_suite
# 단일 workflow 폴더도 같은 명령으로 사용
python -m raceplan.report results/raw/comparison --output-dir results/reports/comparison
```

`index.html`을 브라우저로 연다. images/와 provenance.json을 포함한 폴더 전체를 복사하면
입력 프로젝트 없이도 리포트를 볼 수 있다. HTML 링크는 생성한 상대경로만 사용한다.
기존 output-dir은 거부하며 입력 결과를 수정하거나 계획/주행을 다시 실행하지 않는다.

## 표와 분모

첫 표에 도달/기록 수, 충돌, timeout, 계획 실패와 그중 planning_error를 표시한다.
RMSE/주행시간 중앙값은 도달한 episode만 계산하고 n을 표시한다. reported/runner
계획시간은 case별 plan1회로 중복을 제거하며 구 결과에 없는 runner 값은 n/a다.

paired RMSE/시간 delta는 같은 case/seed의 양쪽이 도달한 경우, clearance delta는
양쪽이 주행한 경우만 집계하며 각각의 n을 표시한다. delta는 planner−baseline이다.
작은 지도/seed 수의 중앙값을 일반 성능 우위로 해석하지 않는다.

suite의 완료 case만 표와 대표 선정에 포함한다. 실패/중단 case는 별도 coverage 표에
예상/raw/포함/missing 수와 phase·원인을 표시한다. missing을 실패 episode로 꾸미지
않으며 coverage가 불완전할 때 표의 도달률은 전체 실행 성공률이 아니다.
개별 workflow가 미완료인 경우도 집계 없이 실패/누락 상태를 보여 준다.

## 대표 선정과 종료점

planner당 최대3개 PNG만 생성한다. 동일 seed의 모든 planner 이미지를 반복 생성하지 않는다.

1. 성공: 도달 episode 중 RMSE가 가장 큰1개.
2. 주행 실패: collision을 timeout보다 우선해1개.
3. 계획 실패: planning_error 우선, 나머지는 status 순으로1개.

동률은 case id, seed, episode id 순으로 고정한다. 카드에 case/seed/outcome과 선택
이유를 표시한다. 회색은 계획, 청록색은 실제 저장 궤적이다. 주황 X는 마지막 실제
기록 pose이며 provenance에도 좌표/시간을 기록한다. 지도 밖 종료점은 프레임에서
잘릴 수 있지만 좌표는 그대로 보존한다. 계획 실패는 주행/종료 pose 없음으로 표시한다.
해당 범주의 episode가 없으면 빈 범주라고 명시하고 이미지를 만들지 않는다.

## 입력 확인과 보존

저장 analysis의 input hash를 현재 요약/manifest/경로/궤적과 대조하고 지도 YAML/image
hash도 확인한다. episode 결과 분류는 원본 요약과 대조한다. 같은 case/seed의 baseline과
짝을 다시 맞춰 결과 분류, 도달/주행 조건, delta를 검증한다. Clearance delta에는 저장된
episode clearance를 사용한다. 불일치하면 출력 폴더를 만들기 전에 중단한다.
`comparison_manifest.json`과 `analysis/`가 있는 단일 폴더 또는 suite 폴더를 받는다.

provenance.json에 읽은 파일 hash, 현재 생성기 소스 hash, 당시 batch 소스 hash,
coverage와 대표 선정 정보를 기록한다. 당시 소스 hash가 현재와 달라도 읽기를 거부하지
않는다. HTML의 사용자 이름/진단은 escape하고 PNG 텍스트는 기존 renderer helper로
한 줄/폭을 맞춘다. 보존된 원본·봉인 기록은 바꾸지 않는다. 검증 결과는 HANDOFF에 기록한다.
