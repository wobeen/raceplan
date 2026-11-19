# 작업 인계 — 2026-11-20

## GUI 3단계 (2): watch (브랜치 feature/gui-run) — 3단계 완료

플래너 파일을 저장할 때마다 같은 비교를 다시 실행한다. 대화상자의 watch 선택, `raceplan-watch` CLI(새 콘솔 스크립트, `raceplan/gui/watch.py`),
목록 자동 갱신("새" 표시). 계약은 `docs/GUI_PLAN.md` 3-2. GPT 한도가 계속되어 3-1과 같이 설계 Claude, 독립 검증 Claude 리뷰어 2개.
둘 다 P1 없음. 정확성 P2(`--once`가 Windows에서 Ctrl+C를 실행 끝까지 무시하고 0 반환) → 짧은 join 반복·130 반환(실측 1.3 s, 기록 Cancelled).
P3 반영: `--once` 신호 처리, watch 끄기와 새 실행 경합, 취소 기록 문구, on_event 예외로 watch가 조용히 죽음, 목록 갱신 실패·"새" 표시 오판·
빈 목록 안내 잔류, 탐색기·CLI의 같은 초 폴더 이름 충돌, 다른 사용자 소유 파일(POSIX), 큰 파일 매초 해시, 콘솔 인코딩. 폴더 누적은 안내로 둠.
테스트 **146 passed**(watch 4개: 실제 저장→취소·재실행·끄기, 디바운스·되돌림·삭제 후 복원·죽은 watch·끄기 경합, 큰 파일 거부, CLI --once 성공·실패).
실측: CLI watch(느린 저장 중 수정 저장→이전 실행 취소→새 실행 완료, Ctrl+Break 종료 0), 브라우저(omp): watch 시작→완료 결과가 열림, 저장마다
새 작업을 따라감, 포커스 유지, 큰 파일 "실행 안 함" 표시, 원래 내용으로 되돌리면 재실행 없음, watch 끄기, 다른 창 CLI 결과가 3초 안에 "새"로 나타남.
헤드리스 Edge 1280×720 스크롤 없음. 미검증: Linux·macOS(파일 소유자 검사·프로세스 그룹), 네트워크 드라이브·클라우드 동기 폴더의 파일 시각,
Astra 독립 검증(한도 해제 후).
후속 수정: 인자 없이 `raceplan-gui`를 실행하면 `results/raw`가 없을 때 시작하지 못하던 문제 → 기본 경로일 때만 빈 폴더를 만들고 시작
(직접 준 경로는 계속 오류). 거절한 POST의 본문을 읽지 않고 닫아 Windows에서 클라이언트가 응답을 못 받던 간헐 문제(재현 13/300 → 0/300) 수정.

## GUI 3단계 (1): 실행 연결 (브랜치 feature/gui-run, main d9e87d3 기반)

GUI에서 새 비교를 실행한다(`+ 새 실행` 대화상자 → 별도 프로세스 → 진행·로그·취소 → 완료 시 새 run 열기). 계약·보안은 `docs/GUI_PLAN.md`
3단계 기록. 새 모듈 `raceplan/gui/jobs.py`(작업 실행), `raceplan/gui/workflow_runner.py`(workflow 상태 저장 재시도 래퍼).
`raceplan-gui`에 `--scenarios`(기본 `scenarios`), `--no-run`, `--run-timeout`(기본 900 s)을 추가했고, 출력 주소에 `#token=…`이 붙는다.
**GPT(openai-codex) 사용 한도**로 설계(sol)·검증(Astra)을 못 해 사용자 결정에 따라 설계는 Claude, 독립 검증은 Claude 보안 리뷰어·정확성
리뷰어 에이전트가 맡았다. 둘 다 P1 없음. 보안 P2(같은 PC의 다른 계정·프로세스가 페이지에서 토큰을 얻어 실행 가능) → 토큰을 페이지에서 빼고
주소 조각으로만 전달. 정확성 P2 3건(서버 종료 시 기록 누락, 기록 실패 시 작업이 영원히 실행 중, Windows 읽기와 상태 저장 충돌) → shutdown이
기록까지 대기·상태 게시는 finally·`workflow_runner` 재시도 래퍼. 마지막 충돌은 테스트에서 실제로 재현됐다(모든 phase가 끝났는데
workflow.json이 running으로 남고 종료 코드 1). P3(프로세스 트리 종료, `-P`, 줄 길이 제한, 끝난 작업 정리, 이상한 JSON 400, 정상 종료와 취소
경합, reader join, 취소 응답 덮어쓰기, 로그 선택, Esc·Tab, 테스트 보강)도 반영했다.
테스트 전체 **142 passed**(기존 137 + 실행 5: 보안 거부, 요청 검증, 실제 subprocess 실행, 단일·취소·시간 초과·종료 기록, 저장 재시도),
실제 실행·취소 테스트는 5회 반복 모두 통과. 브라우저(omp, 임시 결과 폴더): 대화상자로 examples/my_planner.py 포함 실행→완료→새 run 열림,
느린 플래너 취소→목록에 failed, 로그의 HTML이 글자로 표시, 토큰 없는 탭은 읽기 전용, 토큰 주소로 열면 실행 가능·주소에서 토큰 제거·새로고침
후 유지, `--no-run` 비활성, Esc·알약 재열기. 헤드리스 Edge 1280×720 스크롤 없음.
미검증: Linux·macOS(프로세스 그룹 kill·SIGHUP), 실제 다중 사용자 PC, 사용자 플래너가 띄운 손자 프로세스 정리(Windows taskkill /T 경로는
코드만), Astra 독립 검증(한도 해제 후 받을 예정).

## GUI 2단계 (5): 겹친 점 seed 선택·표↔차트 선택 연동 (브랜치 feature/gui-compare) — 2단계 완료

산점도는 원본 (x, y)가 같은 점을(planner 무관), Paired Δ는 같은 레인의 같은 Δ를 ×N 표식으로 묶고, 마우스·키보드로 seed를 고르는 목록을
연다. 차트 아래 상태줄은 선택이 점으로 보이는지와 아닌 이유를 서버의 additive 사유 필드(`scatter.excluded`, `paired_delta.excluded_pairs`)로
보여 준다. 탐색 표는 "표시 n / 전체 m행"과 숨은 선택 안내·[전체 보기로 전환]을 보이고, 선택이 바뀔 때만 선택 행으로 스크롤한다.
설계 gpt-6.2-sol, 구현 Claude, 검증 gpt-6.2-astra(P1 없음). P2 5건 중 4건(로딩 중 이전 목록 확정, 대기 중 낡은 상태줄·`.rph` 입력, Tab 이탈 시
열린 목록·다른 키 keyup, 상태줄 높이 전 SVG 측정)과 P3 3건(표 스크롤 키의 run, 리사이즈 후 포커스, 사유 대응 테스트)을 고쳤다.
미수정: 2^53을 넘는 seed의 JS 정밀도(실제 seed 범위 밖, 이전 스텝과 같은 판단). 테스트 전체 **137 passed**(기존 136 + 사유 1, 기존 합성 테스트에 사유 대응 단언 추가).
브라우저(omp)로 실데이터 turn_aware_20261103/clean(산점도 묶음 5·Δ 묶음 4)과 holdout q0에서 확인했다: 마우스·키보드 확정(history +1, 포커스 복귀),
Space로 열어도 즉시 확정 안 됨, Esc·Tab 이탈 시 무변경으로 닫힘, planner 칩·기준 planner·계획 오류 사유 문구, 응답 지연 중 busy와
"불러오는 중" 상태줄, run 전환 시 목록 닫힘, 숨은 선택 안내와 전체 보기 전환(push 1, 행 스크롤), 차트 선택 뒤 탐색 진입 시 행 스크롤,
일반 재렌더의 스크롤 유지, 리사이즈 뒤 같은 점 포커스. 헤드리스 Edge 1280×720 스크롤 없음, SVG 높이 = 차트 영역.
미검증: 결과가 섞인 Δ 묶음(마름모)의 실데이터 사례(합성만 가능), 화면 판독기 실제 낭독, 수정 후 Astra 재검토.

## GUI 2단계 (4): 에피소드·coverage CSV 내보내기 (브랜치 feature/gui-compare)

`GET /api/export/episodes.csv`(현재 case, 탐색 표 필터와 같은 조건의 모든 행, 저장 헤더·값·순서 그대로)와 `GET /api/export/coverage.csv`
(run의 모든 case, 미완료 포함)를 추가했다. 계약은 `docs/GUI_PLAN.md`. 설계 gpt-6.2-sol, 구현 Claude, 검증 gpt-6.2-astra.
Astra P1(해시를 run 전체에서 경로로 찾아, case A 경로가 B 파일을 가리키면 B 행이 A 이름으로 나갈 수 있음)은 case별 경로·해시 고정과
경로 변경 거부로, P2 5건(coverage 캐시 낡음, 필수/중복 쿼리, 전환 중 버튼, `+INF`·BOM 뒤 수식, 빈 레코드·중복 헤더)과 P3 3건(전역 클릭
캡처, 긴 파일명의 접미사 잘림, 테스트 빈틈)을 고쳤다. 테스트 전체 **136 passed**(기존 133 + 내보내기 3).
브라우저(omp)에서 내려받은 파일을 저장 원본과 대조했다: workflow_step2 실패만(6행)·suite_step3 open 도달만이 저장 파일의 해당 행과 동일,
suite coverage가 저장 `coverage.csv`의 수·상태와 동일, BOM·CRLF, 한글 run 파일명, 수식 경고 취소 시 저장 안 됨·확인 시 저장, run·case
전환 중 버튼 비활성, 내려받기 후 history 변화 없음. 헤드리스 Edge 1280×720 스크롤 없음. 미검증: case 파일을 심볼릭 링크로 바꾸는 경우
(Windows 권한 문제로 테스트는 다른 case 바이트로 덮어쓰기로 대신), Excel에서 실제로 여는 동작, 수정 후 Astra 재검토.

## GUI 2단계 (3): 화면 상태 URL 저장·복원 (브랜치 feature/gui-compare)

run·case·seed·Inspector planner·탐색/비교·패널·표 필터/정렬·트랙 표시·비교 지표/X축/결과/planner·seed 필터·재생 A/B/속도·시각을
주소에 담는다(스키마는 `docs/GUI_PLAN.md`). 시각만 바뀌면 `replaceState`, 다른 조작은 `pushState` 한 번이며, 첫 진입과 뒤로/앞으로는
같은 `restore()`로 기본값에서 시작해 값을 검증한다. 맞지 않는 값은 기본값으로 대체하고(없거나 중복인 run·case는 대체하지 않음) 상단
"링크 설정 N개" 알약과 상세로 알린다. 기존 `?run=` 링크는 그대로 동작한다. 서버 변경은 없다(pytest 1줄: 쿼리가 붙은 `/`도 같은 페이지).
설계 gpt-6.2-sol, 구현 Claude, 검증 gpt-6.2-astra. Astra P1(느린 복원 중 사용자 조작 시 주소와 화면 불일치)과 P2 7건(재생 중 run 전환 시
"새 run + 이전 case" 중간 항목, 늦게 실패한 이전 case 오류 표시, 응답 전 속도 변경 시 링크 시각 유실, 짧은 링크에서 첫 스크럽이 push,
재생 불가 case의 패널 미기록, 탐색 경유 B 동기화 누락, 중복 run·case와 `metric=constructor`), P3 3건을 고쳤다. 미수정: 쉼표 이름
planner의 HTTP 왕복 테스트(쉼표 이름 custom planner fixture가 필요, 기존 분석 함수 테스트로 대신).
테스트는 전체 **133 passed**(테스트 수 변화 없음, 기존 페이지 테스트에 공유 링크 단언 추가). URL 복원은 브라우저 로직이라 pytest 대상이 아니며
omp 브라우저 탭에서 확인했다: 조작 3회 = history 3개와 뒤로 6회·앞으로 정확 복원, 짧은 `?run=`에서 첫 스크럽은 replace, 재생 링크 `t=6.3`
복원과 응답 지연 중 속도 변경 후에도 유지, 새로고침 왕복 동일, 잘못된 값 7종과 중복 run 경고, 없는 run·case 대체 없음, `/api/case` 지연 중
뒤로+탭 클릭 시 주소·화면 일치, 재생 중 run 전환은 history 1개이고 뒤로 시 직전 시각 복원. 헤드리스 Edge 1280×720에서 복합 링크 화면
스크롤 없음. 미검증: 쉼표·공백·한글 이름 planner의 실데이터 왕복(해당 결과 없음), Chrome 외 브라우저, 수정 후 Astra 재검토.

## GUI 2단계 (2): 나란히 재생 (브랜치 feature/gui-compare)

비교 탭에 세 번째 패널 "나란히 재생"을 추가했다. 같은 case·seed의 planner 두 개를 같은 지도 범위·축척(같은 `viewBox`·같은 SVG 크기)에서
한 시계로 재생하며, 상태 전이(첫 표본 전·주행 중·종료·기록 없음)와 분모는 `analysis.replay()`가 저장 표본에서 계산해
`/api/compare/replay`로 준다. 설계안은 gpt-6.2-sol, 구현은 Claude, 독립 검증은 gpt-6.2-astra가 맡았다. Astra는 P1 1건(마지막 시각이
비어 있는 궤적에서 화면 예외)과 P2(재생 중 Inspector 값이 첫 표본 전·종료 뒤를 구분하지 않음, 요청 중 이전 재생 버튼 동작, 빈 run 전환 시
이전 재생 그리기, 다른 패널에서 고른 planner와 지도 불일치)·P3(슬라이더 End가 마지막 시각에 닿지 않음)를 지적했고 모두 고쳤다.
고치지 않은 지적: 2^53을 넘는 seed의 JS 정밀도(실제 seed 범위 밖), 에피소드 행 누락 시 run 전체 422(기존 무결성 계약 유지, 문서화),
A/B 차량 위치를 브라우저에서 단언하는 테스트(브라우저 테스트 도구가 없어 아래 수동 확인으로 대체).
테스트는 전체 **133 passed**(기존 130 + 재생 3), Windows TEMP를 basetemp로 사용했다. 헤드리스 Edge 1280×720에서 스크롤 없음을,
omp 브라우저 탭에서 슬라이더 클릭·키보드(End/←/Home)·4× 재생 끝까지·A/B 머리줄 Enter·seed 전환·Starting grid 선택→B 전환과
`/api/case` 응답을 바꿔 넣은 무효 궤적 화면(예외 없음)을 확인했다. 실데이터: holdout evaluation_offset_islands_q0(충돌 vs 도달),
workflow_step2(계획 오류 쪽 "주행 기록 없음"). 미검증: 첫 표본이 0초보다 늦은 실데이터가 없어 `waiting` 상태는 합성 pytest로만 확인,
수정 후 Astra 재검토는 받지 않았다. 남은 일은 `docs/GUI_PLAN.md` 2단계 기록을 따른다.

## GUI 2단계 (1): 비교 분석 탭 (브랜치 feature/gui-compare, feature/gui-explorer 기반)

비교 탭에 Paired Δ strip plot과 산점도를 추가했다. 집계는 `raceplan/gui/analysis.py`가 저장 결과만으로 계산하며
계획·주행을 호출하지 않는다. 설계안은 GPT(gpt-6.2-sol)가, 구현은 Claude가, 독립 검증은 GPT(gpt-6.2-astra)가 맡았다.
Astra가 P1 2건(빈 필터가 전체 집계로 바뀜, coverage 값의 HTML 삽입 가능성)과 P2(쉼표 이름, 응답 경쟁, 기준 planner 표시,
포커스 유실, 테스트 빈틈)를 지적했고 모두 수정했다. 테스트는 전체 **130 passed**(기존 120 + 비교 10),
Windows TEMP를 basetemp로 사용했다. 헤드리스 Edge 1280×720에서 Δ·산점도 화면의 스크롤 없음과 분모·제외 사유 표시를 확인했다.
미검증: 실제 마우스·키보드 조작(점 선택, 필터 클릭)은 스크립트로 하지 않았다. 2차 Astra 재검토는 받지 않았다.
남은 일은 `docs/GUI_PLAN.md` 2단계 기록을 따른다.

## GUI 1단계: 저장 결과 탐색기 (브랜치 feature/gui-explorer)

계획과 목업은 `docs/GUI_PLAN.md`, `docs/gui/mockup.html`. 새 `raceplan.gui`/`raceplan-gui`가
저장된 workflow/batch/suite를 읽어 리더보드, 에피소드 표, 트랙, 타임라인, Inspector를 보여 준다.
검증은 `report._load`를 재사용하므로 변조된 결과는 열리지 않고, 계획·주행을 호출하지 않는다.
서버는 127.0.0.1 전용, GET 전용이며 Host를 검사한다. 신규 의존성은 없다.

전체 **120 passed (16.02s)**(기존 113 + GUI 7), Windows TEMP를 basetemp로 사용했다. 헤드리스 Edge로
실제 결과와 임시 결과를 확인했다: suite_step3(도달만), holdout validation_offset_islands_q0(충돌,
planner 5개), 계획 오류 메시지에 HTML을 넣은 batch(실행되지 않고 글자로 표시), 변조 batch(오류 표시).
창 폭 약 870·1250·1890px에서 패널 잘림 0이다. 재생·정지·타임라인·지도/실행 전환·표 선택은 스크립트
이벤트로 확인했고 실제 마우스 드래그는 하지 않았다. wheel에 `static/index.html`과 진입점이 포함되고
압축을 푼 패키지로 서버가 동작함을 확인했으나, 오프라인 캐시 부족으로 새 가상환경 설치는 못 했다.
macOS·Linux와 Chrome·Firefox는 미검증이다. Astra 독립 검토는 받지 않았다.

주의: 저장소를 옮긴 뒤 `.venv`의 editable 설치가 옛 경로 `Desktop\raceplan\src`를 가리켜서
`.venv\Scripts\raceplan-*.exe`가 동작하지 않는다. 다시 설치하거나 `PYTHONPATH=src`로 실행한다.

## 현재 커밋 원칙과 다음 개발

2026-11-04 사용자 지시: 지금까지 RacePlan 작업을 커밋하고, 이후에는 개발 스텝
하나를 완료·검증할 때마다 해당 변경을 커밋한다. 과거의 사용자 직접 staging/commit
원칙은 이 지시로 대체된다. push는 별도 요청 시 진행한다.
다음 스텝은 실행 명령 통합 → 사용자 플래너 오류 처리·실측 계획시간 → 여러 시나리오
일괄 비교 → 결과 화면 개선 → 설치·문서·보관 기준 마무리 순서다.
각 스텝에서 구현을 마친 뒤 테스트를 묶어서 실행하고 검증 결과를 기록한다.
RacePlan과 무관한 .pptx-build/ 및 output/ 발표 자료는 이번 커밋에서 제외한다.

## 스텝5: 새 Windows 환경 설치 및 결과 보관 기준

Windows x64의 CPython 3.13.7과 uv 0.12.10을 사용했다. 임시 폴더에 프로젝트
소스·`uv.lock`·로컬 캐시를 복사하고 `uv sync --locked --offline --extra dev --no-editable`로
새 가상환경에 설치했다. setuptools 84.0.0이 만든 `py3-none-any` wheel을 설치했고
`raceplan`이 새 환경의 `site-packages`에서 로드됨을 확인했다. NumPy 2.5.4,
Pillow 12.3.0, PyYAML 6.0.3, pytest 9.1.1을 사용했다. 기존 `.venv`와 원본 lock은
그대로 유지했다.

저장소 밖의 작업 디렉터리에서 `PYTHONPATH`를 제거하고 pytest의 `pythonpath` 설정을
비활성화한 상태로 전체 **113 passed (18.20s)**와 설치 콘솔 명령을 한 묶음으로 검증했다.

| 명령 | 검증 결과 | 로컬 출력 |
|---|---|---|
| `raceplan-workflow` | 데모 9/9 도달, PNG 생성 | `results/raw/install_step5_20261105/workflow/` |
| `raceplan-suite` | 데모·open 두 case 완료, 사용자 예제 포함 16/16 도달, 누락 0 | `results/raw/install_step5_20261105/suite/` |
| `raceplan-report` | 저장 suite 16행 포함, 대표 PNG 4장, 계획·주행 재실행 0회 | `results/reports/install_step5_20261105/index.html` |

새 설치 검증 범위는 Windows CPython 3.13.7의 uv 잠금 설치다. README의 pip 경로와 다른
Python 버전·운영체제는 이번에 별도로 검증하지 않았다. 예제 입력은 저장소 파일을 사용했다.
설치·진입점·예제 코드 수정 없이 README 한·영 사용 흐름과 결과 보관 정책을 정리했다.
`results/reports/`를 Git 제외 목록에 추가했다. 기존 원본과 봉인 산출물은 보존했다.
Astra가 설치 메타데이터, 설치 소스 43개 hash, 콘솔 산출물과 보관 기준을 대조해
최종 승인했다. 이번 설치 검증으로 계획한 스텝 1~5를 모두 마쳤다.

## 스텝4: 저장 결과 정적 HTML·대표 궤적 구현

새 `raceplan.report`/`raceplan-report`가 workflow/batch/suite의 저장 결과만 읽어
새 output-dir에 실패 우선 비교표·coverage·조건부 paired 통계와 대표 PNG를 만든다.
planner당 worst-RMSE 성공/주행 실패/계획 실패 각1개로 제한하고 case/seed/outcome/이유와
마지막 실제 pose를 표시한다. 실패 suite case는 coverage/사유로 남기고 집계에 넣지 않는다.
원본 입력/지도 hash를 검증하고 source/input hash를 provenance에 기록한다. 당시 소스가
현재와 달라도 허용하며 모든 링크는 생성한 로컬 상대경로다. 재계획/주행 재실행은 없다.
기존 selected-seed PNG와 실행 모듈을 보존했다. Astra가 지적한 파생 CSV 검증 누락을
수정했다. 원본 요약으로 episode 결과 분류를 확인하고, 같은 case/seed baseline과의 짝에서
coverage, 결과, 도달/주행 조건, 유한 delta를 검증한다. Clearance는 저장 episode 값을 쓴다.

초기 묶음은 Windows 기본 인코딩으로 인한 테스트 읽기 오류를 UTF-8 지정으로 수정했다.
이후 OneDrive WinError 5와 샌드박스 TEMP 권한 오류를 피해 승인된 Windows TEMP에서
관련 14개, 전체 112개와 저장 리포트 smoke 3건을 통과했다. P2 수정 후 같은 방식으로
관련 **15 passed (9.18s)**, 전체 **113 passed (12.72s)**와 저장 smoke 3건을 확인했다.
최종 산출물은 `results/raw/report_step4_{suite,errors,collision}_20261105_reviewed/`에 있다.
각각 16행·PNG 4장, 18행·PNG 6장, 15행·PNG 5장이다. 오류 batch의 대표 계획 실패
두 건에는 종료 pose가 없고, holdout batch의 대표 충돌 두 건은 마지막 저장 pose를 표시한다.
세 산출물 모두 계획/시뮬레이션 호출 0회이며 초기 smoke는 별도 경로에 보존했다.
Astra가 최종 입력·생성기·출력 hash, 집계 분모, 대표 선정과 종료 좌표를 대조하고
승인했다. 새 환경 설치와 데이터 보관 기준은 스텝5에 기록했다.

## 스텝3: 설정 YAML suite 구현

6.1-sol이 새 `raceplan.suite`/`raceplan-suite`를 추가했다. strict YAML/schema와 안전
고유 case id, 설정 기준 상대경로, 공통 옵션을 사전 검증하고 기존 workflow를 순차 호출한다.
완료 case만 episodes/planning/paired와 전체·case별 집계에 합치며 plan 시간은 seed 중복을
제거한다. 실패 case는 예상/raw/포함/missing coverage를 기록하고 빈 episode를 만들지 않는다.
일반 case 오류는 다음 case를 실행한 뒤 최종 nonzero, control exception은 suite 중단과
not_run coverage로 처리한다. 기존 실험/분석/리포트/봉인 파일을 보존했고 workflow의
구조화된 control_exception 필드만 additive로 추가했다.
예제 `examples/suite.yaml`, 사용·스키마·정책 `docs/SUITE.md`, 핵심 회귀4개를 작성했다.
구현 완료 뒤 관련/전체 pytest와 demo/open suite smoke를 한 묶음으로 실행한다.
구현 에이전트 staging/commit 없음. 검증·Astra·커밋 기록은 다음 단계다.

구현 중 테스트0회, 구현 완료 뒤 관련17 passed(6.72s), 전체108 passed(8.95s),
예제 suite smoke1회를 묶어 실행했다. demo/open2case16행 모두 도달, 실패/missing0,
planning8행(각case/planner1회), paired12행을 확인했다. 두 PNG 시각검토 완료.
출력 `results/raw/suite_step3_20261105/`. 상대경로·대시 이름·custom 오류·strict 입력·
부분 실패 coverage·control exception 회귀를 통과했다. 초기 구현 시 기존 모듈 diff0,
diff --check 통과. 이후 workflow 중단 필드를 아래와 같이 보완했다.

Astra P2로 workflow에 error.control_exception bool을 추가하고 suite가 해당 플래그로
중단을 판정한다. CustomInterrupt/CustomExit도130/7로 중단하고 일반 RuntimeError는
False임을 E2E로 확인했다. 첫 수정 후 관련 묶음은 os.replace의 WinError5로1실패·16통과,
전체 미실행이었다. 추가 코드 수정 없이 관련+전체를 다시 묶어 실행해 관련17 passed
(3.95s), 전체108 passed(7.12s)를 확인했다. 초기16행 smoke는 수정 전 출력으로 보존했고
최종 중단 수정은 서브클래스 E2E로 구분한다. Astra 최종 승인 완료: 초기 smoke의
입력8·소스42 hash와16 episode/8 plan/12 pair 집계, 최종 중단 수정과 테스트를
독립 확인했고 잔여 차단 결함은 없다. 스텝3 완료 후 커밋한다.
스텝4의 결과 비교표와 대표 성공·실패 궤적은 위 절에 기록했다.

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
