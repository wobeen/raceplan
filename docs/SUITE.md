# 설정 파일로 여러 시나리오 비교

저장소 루트에서 실행한다. 설치 후 `raceplan-suite`도 같은 인자를 받는다.

```powershell
python -m raceplan.suite examples/suite.yaml --output-dir results/raw/my_suite
```

[예제 YAML](../examples/suite.yaml)은 demo와 validation_open을 기본3종+MyPlanner,
seed0/1로 순차 실행한다. 총16행이며 새 지도 생성이나 튜닝은 하지 않는다.
현재 소스에서 직접 실행하려면 먼저 `$env:PYTHONPATH = (Resolve-Path src).Path`를 설정한다.

## 설정

필수 항목은 `version: 1`, 비어 있지 않은 `cases` 목록이다. 각 case는 `id`, `scenario`만
받는다. ID는 영문/숫자로 시작하는 최대64자의 영문·숫자·`_`·`-` 문자열이고,
대소문자를 무시해 고유해야 한다. Windows 예약 이름(CON, NUL, COM1 등)은 거부한다.
scenario와 custom 파일의 상대경로는 YAML 위치 기준이다. scenario 내부 지도 경로는
기존처럼 scenario 파일 기준이다. Windows 드라이브 콜론은 custom spec의 마지막
콜론으로 클래스명을 분리해 보존한다.

공통 옵션은 모든 case에 적용한다. per-case 옵션 덮어쓰기는 제공하지 않는다.

| 키 | 기본값/의미 |
|---|---|
| planners | 기존 Dijkstra/A*/Hybrid A*; 비어 있지 않은 고유 목록 |
| custom_planners | `file.py:Class` 목록, 기본 빈 목록 |
| simulation_seeds | 생략하면 각 scenario의 simulation_seed1개; 지정 시 고유 비음수 정수 목록 |
| noise | NoiseConfig의 underscore 필드 mapping, 생략 필드는0 |
| inflation_radius_m | 0, 유한 비음수 |
| baseline | 선택한 A*, 없으면 첫 builtin; custom 이름은 완료 manifest에서 확인 |
| report_seed | 각 case의 첫 seed; 지정 시 모든 case seed에 포함되어야 함 |
| spacing_m | 0.1, 유한 양수 |

알 수 없는 키, 중복 YAML 키, 잘못된 타입/경로/ID/seed는 실행 전에 거부한다.
custom 코드는 미리 import하지 않아 파일 구문/생성/config와 동적 이름 오류는 실행 시
드러날 수 있다. 사용자 파일은 신뢰된 코드만 사용한다.

## 출력과 집계

새 output-dir만 허용한다. `resolved_config.json`에 절대경로와 case별 seed를 기록하고,
`provenance.json`에 설정·지도·scenario·custom·소스 hash를 남긴다. 입력 hash는 각 case
시작 전에 다시 확인한다. `config_snapshot.yaml`은 실행 설정 사본이다.

- `cases/<id>/`: 기존 workflow의 CSV/manifest/analysis/PNG/상태를 그대로 보관한다.
- `suite.json`, `coverage.csv`: 각 case의 상태·실패 phase·예상/원시/집계 포함/누락 행 수.
- `episodes.csv`: 완료 case의 분석 행과 case/scenario/planner/seed 식별키.
- `planning.csv`: `(case_id, plan_id)`당1행으로 seed 중복을 제거한 reported/runner 시간.
- `paired.csv`: 같은 case/seed의 기존 paired 지표와 전역 pair_key.
- `case_summary.csv`, `summary.csv`: case별/전체 planner의 기록 수·도달·충돌·timeout·계획 실패/오류.

전체 성공 지표는 기록된 도달 episode만 사용한다. `reach_rate_observed`의 분모는
집계에 포함된 episode다. 전체 summary에 coverage_complete와 기대/완료/실패 case 및
missing_episode_count를 같이 기록한다. 누락이 있으면 전체 실행의 성공률로 해석하지 않는다.
paired delta의 양쪽 도달/주행 조건은 기존 분석기를 따른다. 시간 통계는 case당 plan1회만
세며 seed 수를 timing sample 수로 사용하지 않는다. 작은 P95는 기술통계다.

## 실패와 중단

custom의 일반 plan 오류는 기존처럼 planning_error 데이터로 남고 case는 정상 완료된다.
일반적인 case 인프라/실행/수집 오류는 failed로 기록한 뒤 다음 case를 진행한다.
완료 workflow만 suite 집계에 포함한다. report만 실패해도 해당 case의 기존 CSV는 보존하고
집계 포함 수0, missing 수는 기대 수로 기록한다. 빈 episode를 만들어 실패를 채우지 않는다.

case 실패가 있으면 종료코드1이며 일부 완료 시 partial, 모두 실패 시 failed다.
KeyboardInterrupt는 종료130, SystemExit는0을 제외한 해당 종료코드로 suite 전체를 중단한다.
workflow가 SystemExit로 보고한 argparse 종료도 같은 중단 정책을 적용한다.
workflow의 구조화된 `error.control_exception` 플래그를 사용하므로 두 예외의 서브클래스도
같은 중단 정책을 적용한다. 일반 오류는 False이고 다음 case를 계속한다.
뒤 case는 not_run으로 남기고 가능한 완료 결과/coverage를 저장한다. SystemExit(0)은
미완료 suite이므로1을 반환한다. 같은 폴더 자동 재시도/재개는 제공하지 않는다.

기존 실험/분석/리포트와 봉인 자료는 보존한다. workflow에는 구조화된 중단 플래그만
additive로 추가했다. suite는 여러 개발 시나리오의 편의 집계이며
새 held-out 평가나 독립적인 표본 수 증가를 뜻하지 않는다. 검증 결과는 HANDOFF에 기록한다.

2026-11-05 구현 완료 뒤 관련17 passed(6.72s), 전체108 passed(8.95s), 예제 suite
smoke1회를 묶어서 실행했다. demo/open2case의16행 전부 도달했고 실패/missing0이다.
episodes16행, seed 중복을 제거한 planning8행, paired12행과 case/전체 집계를 확인했다.
두 PNG를 시각검토했고 결과는 `results/raw/suite_step3_20261105/`에 보존한다.
회귀4개는 상대경로·custom 오류·식별키·집계, strict 입력 거부, 부분 실패 후 계속 실행과
missing coverage, control exception 중단을 검증한다. Astra 독립 검토는 다음 단계다.

Astra P2 수정으로 workflow의 `error.control_exception`을 isinstance 기반으로 기록하고
suite가 클래스명 문자열 대신 해당 플래그로 중단을 판정한다. CustomInterrupt/CustomExit의
E2E와 일반 RuntimeError의 False 플래그를 검증했다. 수정 후 첫 관련 묶음은 기존 상태파일
교체(os.replace)에서 WinError5로1실패·16통과였고 전체 pytest는 시작하지 않았다.
추가 코드 수정 없이 같은 묶음을 재실행해 **관련17 passed (3.95s), 전체108 passed
(7.12s)**를 확인했다. 초기16행 smoke는 수정 전 결과로 보존하며, 최종 중단 수정은
서브클래스 E2E로 검증했다. Astra는 초기 smoke 입력8·소스42 hash 및16 episode/
8 plan/12 pair의 원본 대조와 최종 수정 검증을 마쳤고, 차단 결함 없이 승인했다.
