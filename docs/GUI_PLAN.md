# GUI 계획: RacePlan Explorer

브랜치 `feature/gui-explorer`. 상태: **계획·목업 단계** (구현 전, 사용자 판단 대기).
목업은 `docs/gui/mockup.html`(샘플 데이터, 브라우저에서 열기).

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

- 저장 궤적: 현재 episode별 전체 sample을 어디까지 보관하는지 확인 필요(없으면
  report처럼 저장된 항목 범위 내에서만 표시하거나 저장 옵션 추가).
- 코드 편집기를 내장할지, 외부 편집기 + watch로 갈지(권장: 외부 + watch).
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
- 스타일: 흰색 기반 리퀴드 글라스(반투명 패널, 배경 블러, 상단 하이라이트, 알약형 컨트롤). 체크박스는 글자 크기에 비례하는 큰 크기.
- 구현 시 주의: 창 비율이 16:9보다 넓으면 폭 기준 배치는 세로 스크롤이 생긴다. 실제 앱은 창 높이까지 고려해 16:9 영역을 맞춘다.
