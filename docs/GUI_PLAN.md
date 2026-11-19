# GUI 계획: RacePlan Explorer

브랜치 `feature/gui-explorer`(1단계), `feature/gui-compare`(2단계). 상태: **1단계(결과 탐색)와 2단계(비교 분석) 완료** — 비교 탭의
Paired Δ·산점도·나란히 재생, 화면 상태 URL 저장·복원, 에피소드·coverage CSV 내보내기, 겹친 점 seed 선택과 표↔차트 선택 연동.
목업은 `docs/gui/mockup.html`(샘플 데이터, 브라우저에서 열기). 목업의 차트 옵션·터미널·코드 패널·
실험 셋 생성·타일 재배치는 뒤 단계 기능이며 실제 앱에는 아직 없다.

1단계에서 목업과 달라진 점: 실험 셋 목록 대신 저장된 실행 목록을 보여 주고, Paired Δ 자리에는
정렬·필터 가능한 에피소드 표를 둔다. 계획시간은 `paired.csv`에 차이 값이 없어 값만 표시한다.
데스크톱 창(`--window`)은 exe와 함께 4단계로 미뤘고, 지금은 브라우저로 연다.

## 목적

비교 실험 수치를 글·정적 PNG로만 보면 분석·활용이 어렵다. 저장된 실험 결과를
직접 걸러 보고, 궤적을 재생하고, planner를 paired로 비교하는 도구를 핵심 기능으로 둔다.
MVP 장난감이 아니라 `raceplan-report`와 같은 층위의 정식 기능이다.

## 원칙

- GUI는 결과를 **읽고 보여주는** 층이다. 계획·주행 로직은 건드리지 않고, 실행은
  기존 `raceplan.workflow`/`suite`를 호출한다(③단계).
- 저장 결과를 재계획·재주행하지 않는다(`report`와 동일). provenance/hash 검증을 재사용한다.
- 집계 분모·coverage·실패(planning_error, 충돌, timeout)를 숨기지 않는다.
- 기존 CLI·CSV 스키마·봉인 산출물은 변경하지 않는다. GUI는 additive.

## 구조

- 백엔드: Python 표준 `http.server` 기반 로컬 서버(127.0.0.1 전용). 신규 의존성 최소화.
  `episodes/paired/planning/coverage.csv`, `provenance.json`, 저장 궤적을 JSON API로 제공.
- 프론트엔드: 정적 HTML/JS(번들러 없음), SVG 렌더링. 기존 HTML 리포트 코드 재사용 검토.
- 진입점: `raceplan-gui [RESULT_DIR]`(브라우저 열기), `--window`(pywebview 데스크톱 창).
- 패키징: optional extra `gui`(pywebview). exe는 PyInstaller로 4단계에서 시도.

## 단계 (각 단계 완료·검증마다 커밋)

1. **결과 탐색** — 폴더 열기, case/planner/결과/seed 필터·정렬, KPI 카드, 행 선택 시
   지도 위 계획 경로+실제 궤적, 시간 슬라이더 재생, 충돌 지점 표시.
2. **비교 분석** — paired Δ 지표 strip plot(제외 쌍 수 표기), 지표 산점도, 두 planner
   같은 시간축 나란히 재생, 차트 점→표 행 연동, 필터 상태 URL 저장·CSV 내보내기.
3. **실행 연결** — 사용자 플래너 선택, 비교 실행, 로그/진행, 파일 변경 감지 시 자동
   재실행(watch), 새 결과 자동 갱신. CLI는 `raceplan watch FILE.py:CLASS` 병행.
   사용자 코드는 별도 프로세스·timeout으로 격리, 임의 코드 실행 경고를 UI에 표시.
4. **exe 배포** — PyInstaller 단일 폴더/exe, 설치 검증 문서.

## 열린 질문

- 저장 궤적(확인 완료): case별 `comparison_trajectory.csv`에 step별 시각·위치·yaw·속도·가속도·조향·
  추적오차가, `analysis/clearance_samples.csv`에 step별 footprint clearance가 있다. 재생과 시계열에
  충분하다. 단 `results/raw/`는 Git 제외라 로컬에만 있다.
- 옆 패널의 터미널·코드 편집기(사용자 요청, 3단계): 목업은 동작 모양만 보여 준다. 실제 구현은 터미널에
  PTY 연결(Windows는 ConPTY)과 xterm.js 계열, 편집기에 CodeMirror 또는 Monaco가 필요하다. 로컬 서버가
  셸을 열게 되므로 127.0.0.1 바인딩과 세션 토큰을 필수로 두고, 라이브러리는 번들 포함 여부를 함께 검토한다.
- 다국어: 한국어 우선, 영어 문구는 이후.

## 검증 방침

기존 규칙대로 구현을 마친 뒤 테스트를 묶어 실행한다. 서버 API는 저장 결과 fixture로
pytest, 화면은 스크린샷 시각 확인. 결과 수치는 `report`/`analyze` 출력과 일치해야 한다.

## 목업 v5 결정 사항 (사용자 피드백 반영)

- 화면: 16:9 고정, 스크롤 없음. VS Code 복제가 아닌 RacePlan 고유 구성
  (실험 셋 · Starting grid · 리더보드 · 트랙 · 텔레메트리 타임라인 · Inspector).
- 리더보드 체크박스: 체크한 알고리즘의 경로만 트랙·타임라인에 표시.
- 지도: 파일(maps/*.yaml)로 불러온 목록에서 선택(썸네일·크기 표시, 파일/폴더 추가).
- 실험 셋: 지도·planner·seed 묶음을 여러 개 만들어 두고 전환. "새 셋" 대화상자로 생성.
  사용자 확정: 셋은 YAML 파일로 저장한다(기존 `examples/suite.yaml` 형식 기준). CLI와 GUI가 같은 파일을 쓴다.
- Paired Δ와 계획시간×RMSE 차트는 선택 옵션(패널 메뉴). 계획시간×RMSE는 기본 숨김.
- 타일은 제목줄을 끌어 자리 교체, ✕로 숨김. 크기 조절은 미정.
- 옆 패널: 상단 버튼으로 터미널(여러 개)과 코드 편집기를 탭으로 열고, 폭을 조절한다.
- Inspector: 지표와 A* 대비 차이, 실패 요약(실패 시에만), 타임라인과 연동되는 시계열(추적오차·clearance·
  속도·조향)을 보여 준다. 차이는 `paired.csv` 규칙을 따른다: RMSE·시간은 둘 다 도달, clearance는 둘 다 주행.
- 스타일: 흰색 기반 리퀴드 글라스(반투명 패널, 배경 블러, 상단 하이라이트, 알약형 컨트롤). 체크박스는 글자 크기에 비례하는 큰 크기.
- 구현 시 주의: 창 비율이 16:9보다 넓으면 폭 기준 배치는 세로 스크롤이 생긴다. 실제 앱은 창 높이까지 고려해 16:9 영역을 맞춘다.
- 타임라인: 화면 높이의 약 17%로 축소. planner 4개가 한계에 가까우므로 5개 이상이면 레인 스크롤이나 접기가 필요하다.

## 2단계 진행 기록 (브랜치 feature/gui-compare)

완료: 상단 `탐색 | 비교` 탭, Paired Δ strip plot(지표 RMSE·완료시간·clearance), 산점도(X 계획시간 로그, Y RMSE),
planner·seed·결과 필터, 점 선택 → Inspector 연동. 집계는 서버(`raceplan/gui/analysis.py`)에서 저장 결과로만 계산하고
`/api/compare/delta`, `/api/compare/scatter`로 제공한다. 필터 값은 키를 반복해 보낸다(`planners=a&planners=b`,
빈 값은 "아무것도 선택 안 함"). 분모(후보 쌍/기록)와 제외 사유(짝 없음·결과 필터·조건 미충족·Δ 없음)는 화면에 항상 표시한다.

설계 대비 변경: 초안은 "새 엔드포인트 없음, 브라우저 집계"였으나 분모·제외 사유를 pytest로 검증하려고 서버 집계로 바꿨다.
`report._load`가 저장 기준 planner를 case에 `baseline`으로 추가한다(additive).

나란히 재생(완료): 비교 탭 세 번째 패널. A/B planner와 상단 seed를 고르면 두 지도(같은 `viewBox`, 같은 CSS 크기)를
한 시계로 재생한다. 시간축은 0초부터 **두 기록 중 늦은 마지막 표본**까지이고, 속도 0.5–4×, 슬라이더(키보드 포함)를 쓴다.
상태 전이는 서버 `analysis.replay()`가 저장 표본에서 계산해 `/api/compare/replay?run&case&a&b&seed`로 준다:
`waiting`(첫 표본 전, 차량 없음) → `driving` → `ended`(마지막 위치·결과·시각 고정, 충돌은 링) 또는 `no_record`
(사유 `missing_episode`/`no_samples`/`invalid_samples`). 첫 표본 전·마지막 표본 뒤의 움직임은 만들지 않으며,
"저장 에피소드 n/2 · 재생 가능 n/2" 분모를 항상 표시한다. 재생 패널에 들어갈 때 현재 선택 planner가 B가 되고(A는 저장 기준),
A/B 머리줄을 누르면 Inspector 대상이 바뀐다. 설계안의 "차트별 별도 재생 버튼"은 이 규칙으로 대체했다.
표본 유효성은 `analysis.trace_valid()` 한 곳에서 정하고 `/api/case` trace에 `valid`로 함께 준다(additive). 무효 궤적은 재생·시계열에
쓰지 않고 "궤적 데이터 오류"로 표시한다. 에피소드 행 누락처럼 저장 결과 무결성이 깨진 경우는 기존 계약대로 run 전체가 422이며,
`missing_episode`/`no_samples`는 무결성을 통과한 결과의 슬롯별 사유다(실제로는 계획 실패가 `no_samples`).

URL 저장·복원(완료): 화면 상태를 주소에 담아 새로고침·링크 공유·뒤로/앞으로로 복원한다. 키는 `run`, `case`, `seed`, `planner`(Inspector),
`view=cmp`, `panel=scatter|replay`, `filter=fail|ok`(표), `sort`·`dir=desc`, `metric`, `x=runner`, `out=reached|fail`(비교 결과), 목록
`track`·`planners`·`seeds`(비교 API처럼 키 반복, 키 없음 = 전체, 빈 값 = 선택 없음), 재생 `a`·`b`·`speed`, 시각 `t`(탐색은 기본값이 끝,
재생은 0). 기본값은 생략한다. 시각 `t`만 바뀌면 `replaceState`(슬라이더·재생 정지 뒤 0.3초에 한 번), 다른 조작은 `pushState` 한 번이다.
첫 진입과 뒤로/앞으로는 같은 복원 경로(`restore`)로 기본값에서 시작해 값을 검증하며, 복원 중에는 주소를 쓰지 않는다.
맞지 않는 값은 기본값으로 대체하고(없는 run·case는 다른 결과로 대체하지 않음) 상단 "링크 설정 N개를 적용하지 못했습니다" 알약과
상세 목록으로 알린다. 기존 `?run=` 링크는 그대로 동작한다. 설계안의 "결과 코드 목록" 대신 표·비교 결과 필터는 화면 선택지 그대로 저장한다.

CSV 내보내기(완료): 서버가 저장 파일에서 만든다(`GET /api/export/episodes.csv?run&case&filter=all|fail|ok`,
`GET /api/export/coverage.csv?run`). 에피소드는 저장 `analysis/episodes.csv`의 헤더·셀 문자열·행 순서 그대로이며, 탐색 표 필터와 같은
조건으로 일치하는 행 전부를 담는다(화면 정렬과 무관, 빈 레코드는 report처럼 건너뜀). 로드 때 case별로 파일 경로와 sha256을 고정하고,
경로가 다른 곳을 가리키거나 바이트가 바뀌면 422다. coverage는 내보낼 때마다 `_load`로 다시 검증해(report와 같은 경로) run의 모든 case
(미완료 포함)를 suite `coverage.csv` 열 이름(`case_id, status, expected_episode_count, raw_episode_count, included_episode_count,
missing_episode_count, failed_phase, error_type, error_message`)으로, 값은 report의 Case coverage 표와 같게 쓴다. 모르는 수는 빈 칸이다.
필수 키(`run`, 에피소드는 `case`)가 없거나 비었거나 반복되면 400이고, coverage에 `case`·`filter`를 주면 400이다.
UTF-8 BOM + CRLF, 파일명은 `filename*`(UTF-8). 공백·제어문자·BOM 뒤에 `=, +, -, @`로 시작하는 값(십진·지수 숫자 제외, 헤더 포함)이 있으면
값은 원본 그대로 두고 `X-RacePlan-CSV-Formula-Risk: 1`을 보내 화면이 저장 전에 확인받는다. 버튼은 에피소드 카드 제목줄과 coverage 알약 안에
있고 run·case 전환 중에는 꺼진다. 내려받기는 주소·history를 바꾸지 않는다.

겹친 점 seed 선택·표↔차트 연동(완료): 산점도는 원본 (x, y)가 정확히 같은 점을 planner와 무관하게, Paired Δ는 같은 레인의 정확히 같은
Δ를 한 표식(×N)으로 묶는다(반올림으로 묶지 않고, 다른 값은 지터로 벌림. 결과가 섞인 Δ 묶음은 마름모). 묶음을 클릭·Enter·Space하면
seed 선택 목록이 열리고(↑↓·Enter·Esc·닫기), 확정만 선택을 바꾸어 history 1개를 남긴다. 비교 데이터를 다시 받는 동안에는 이전 점을 고를 수 없다.
차트 아래 상태줄이 선택(planner·seed)의 점 표시 여부와 사유를 보여 준다. 사유는 서버가 additive 필드로 준다:
`scatter.excluded`, `paired_delta.excluded_pairs`(planner·seed·reason, planner/seed/결과 필터 제외 포함, 기존 카운트와 같은 사유).
탐색 표 위에는 "표시 n / 전체 m행"과, 선택이 표 필터에 숨으면 "선택 행 숨김" + [전체 보기로 전환]을 보이며 숨긴 행을 끼워 넣지 않는다(CSV 범위와 같음).
표는 선택·필터·run·case가 바뀔 때만 선택 행으로 스크롤한다. 새 URL 키는 없다. 설계안의 Inspector 상태줄·버튼은 공간 때문에 넣지 않았다.
목록은 Tab으로 벗어나거나 run·case 전환·재요청·복원 때 닫히고, 로딩 중에는 열기·확정을 막는다. 요약을 먼저 배치한 뒤 차트 영역을 잰다.

## 3단계 진행 기록 (브랜치 feature/gui-run)

3-1 실행 연결(완료): "저장된 실행" 카드의 `+ 새 실행` 대화상자에서 시나리오(서버가 `--scenarios` 폴더에서 찾은 시나리오 YAML),
내장 planner(1개 이상), 사용자 플래너 `FILE.py:CLASS`(줄마다 하나, 상대 경로는 서버를 시작한 폴더 기준, 네트워크 공유 경로 불가), seed, 기준을 골라
실행한다. 사용자 플래너가 있으면 "이 파일의 코드가 이 컴퓨터에서 실행됨" 경고와 신뢰 확인이 필요하고, API도 `trust_user_code: true`를 요구한다.
실행은 GUI 서버가 아니라 `python -P -m raceplan.gui.workflow_runner` 별도 프로세스다. 이 모듈은 `raceplan.workflow.main`을 그대로 부르되
Windows에서 서버가 workflow.json을 읽는 순간 상태 저장(`os.replace`)이 막히면 잠깐 재시도한다(workflow.py는 출처 해시 대상이라 바꾸지 않음).
`-P`는 서버 작업 폴더의 같은 이름 모듈이 import되는 것을 막는다. 한 번에 하나, 시간 제한(`--run-timeout`, 기본 900 s)과 취소가 있고,
멈출 때는 프로세스 트리 전체를 끈다(Windows `taskkill /T`, POSIX 프로세스 그룹). 결과는 `<root>/gui-runs/<시각>-<시나리오>`에 저장되어
기존 탐색·비교 화면으로 열린다. 진행은 workflow.json phase, 로그는 stdout·stderr 끝 400줄(한 줄 2000자, 한 번 읽기 64 KiB 제한).
완료되면 목록을 다시 읽고 새 run을 연다. 시간 초과·취소·서버 종료(SIGTERM·SIGHUP·SIGBREAK 포함)로 멈춘 실행은 서버가 그 폴더의
workflow.json을 workflow 자체의 중단 기록과 같은 형식(status failed, error Timeout/Cancelled)으로 남긴 뒤 종료해, 목록·coverage에 실패로 보인다.
보안: 읽기는 그대로 GET. 실행·취소는 POST만 받으며 Host 검사, Origin이 정확히 이 서버, 세션 토큰(`X-RacePlan-Token`), `application/json`,
본문 16 KiB 이하가 모두 맞아야 한다. 토큰은 페이지·API 응답에 없고 `raceplan-gui`가 열거나 출력하는 주소의 `#token=…`(서버로 전송되지 않는
조각)으로만 전달된다. 페이지는 그것을 이 출처의 localStorage에 두고 주소에서 지운다. 그래서 페이지만 받아 가는 다른 로컬 프로그램·계정은
실행을 시작할 수 없고, 토큰 없이 연 탭은 읽기 전용이다. 시나리오·planner는 서버가 제시한 목록만 받는다. 실행 기능은 `--scenarios` 폴더가
있을 때 켜지고 `--no-run`으로 끈다. GPT 사용 한도 때문에 설계는 Claude, 독립 검증은 Claude 보안·정확성 리뷰어 에이전트가 맡았다(Astra는 한도 해제 후).

다음: 3-2 watch — 플래너 파일 변경 감지 시 자동 재실행, `raceplan-watch` CLI, 새 결과 자동 갱신.
