# RacePlan.exe (Windows) 설치·실행·검증

Python이 없는 Windows x64 PC에서 RacePlan 결과 탐색기와 watch를 쓰는 배포판이다. 압축 파일 하나를 풀어서 쓴다.
Python에 설치한 RacePlan(`raceplan-*` 명령)과 결과·CSV 형식이 같다.

## 설치

1. `RacePlan-<버전>-windows-x64.zip`(약 27 MiB, 풀면 약 63 MiB)과 `.sha256` 파일을 받는다. PowerShell에서 해시를 확인한다.
   `(Get-FileHash .\RacePlan-<버전>-windows-x64.zip -Algorithm SHA256).Hash`가 `.sha256` 파일의 값과 같아야 한다.
   해시는 받은 파일이 게시된 파일과 같은지만 확인한다. 누가 만들었는지는 증명하지 않으니 두 파일 모두 공식 배포처에서 받는다.
2. zip을 마우스 오른쪽 버튼 → **모두 압축 풀기**로 푼다(zip 안에서 바로 실행하지 않는다). 쓰기 권한이 없는 폴더
   (예: `C:\Program Files`)에 두어도 된다. 프로그램은 자기 폴더에 쓰지 않는다.
3. 서명되지 않은 실행 파일이라 처음 실행할 때 SmartScreen이 "Windows의 PC 보호" 경고를 띄울 수 있다. 해시를 확인한
   파일이면 **추가 정보 → 실행**. 회사 PC 정책이 막으면 관리자에게 문의한다(백신·정책을 끄라고 안내하지 않는다).

폴더 구성:

| 경로 | 내용 |
|---|---|
| `RacePlan.exe` | 실행 파일. 더블클릭하면 탐색기가 열린다 |
| `_internal/` | Python 런타임·NumPy·Pillow·PyYAML·RacePlan 소스(건드리지 않는다) |
| `scenarios/`, `maps/` | 예제 시나리오(demo, validation_open)와 지도 |
| `examples/my_planner.py` | 사용자 플래너 예제(복사해서 고친다) |
| `licenses/` | Python·NumPy·Pillow·PyYAML·PyInstaller 라이선스 고지 |
| `BUILD-INFO.txt` | 빌드한 커밋과 도구 버전 |

## 실행

- **탐색기**: `RacePlan.exe`를 더블클릭한다. 콘솔 창이 열리고 브라우저에 탐색기가 뜬다. 콘솔에 주소(`explorer=…#token=…`),
  결과 폴더(`results=…`), 실행 기능 상태(`run=…`)가 나온다. 브라우저가 안 열리면 콘솔의 주소를 복사해 연다.
  `+ 새 실행`은 이 주소(토큰 포함)로 연 탭에서만 동작한다.
- **끄기**: 콘솔 창에서 `Ctrl+C`, 또는 콘솔 창을 닫는다. 진행 중이던 비교는 멈추고(플래너가 띄운 하위 프로세스까지) 결과
  목록에 실패(Cancelled)로 남는다. 브라우저 탭만 닫으면 서버는 계속 돈다.
- **결과 위치**: `%LOCALAPPDATA%\RacePlan\results\raw`(어디서 실행해도 같다). 새 실행은 그 아래 `gui-runs\`에 쌓이며
  자동으로 지우지 않는다. 다른 폴더를 보려면 `RacePlan.exe D:\내결과` 처럼 폴더를 준다. 그 폴더에 쓸 수 없으면 실행을
  시작할 때 어느 폴더에 쓸 수 없는지와 다른 폴더를 지정하는 방법을 알려 준다(다른 폴더로 몰래 바꾸지 않는다).
- **watch(터미널)**: PowerShell에서
  ```powershell
  & 'C:\경로\RacePlan\RacePlan.exe' watch C:\내폴더\my_planner.py:MyPlanner --scenario 'C:\경로\RacePlan\scenarios\demo.yaml'
  ```
  플래너 파일을 저장할 때마다 다시 실행하고 planner별 도달 수를 출력한다. `--scenario`를 여러 번 주거나 노이즈 옵션
  (`--steering-std-rad 0.01` 등, `watch --help`)을 주면 suite로 실행한다. `--once`는 한 번만 실행하고 완료면 0,
  실패면 1, 중단(Ctrl+C)이면 130을 돌려준다.
- 옵션 목록: `RacePlan.exe --help`, `RacePlan.exe gui --help`, `RacePlan.exe watch --help`.

## 사용자 플래너

`examples\my_planner.py`를 내 폴더(공백·한글 경로 가능)에 복사해 `plan()`을 고친 뒤, 탐색기의 `+ 새 실행`에서 파일 경로를
넣고 "클래스 찾기"로 클래스를 고르거나(파일을 읽기만 하고 실행하지 않는다) `C:\...\my_planner.py:MyPlanner`를 직접 적은 뒤
"신뢰" 확인을 체크한다. 플래너 파일의 코드는 실행할 때 이 PC에서 내 권한으로 그대로 실행된다.
신뢰하는 파일만 쓴다(별도 프로세스·시간 제한은 있지만 파일·네트워크 접근을 막는 샌드박스는 아니다).

플래너가 import할 수 있는 것은 **exe에 실제로 들어 있는 것뿐**이다: RacePlan, NumPy, Pillow, PyYAML, 그리고 RacePlan이 쓰거나
플래너가 흔히 쓰는 Python 표준 라이브러리 모듈(`math`, `heapq`, `collections`, `dataclasses`, `itertools`, `random`,
`statistics` 등 — 목록은 `packaging/windows/RacePlan.spec`). 표준 라이브러리 전체가 들어 있는 것은 아니다. 다른 패키지(SciPy
등)나 플래너 옆의 다른 `.py` 모듈은 불러올 수 없다. 그런 import로 실행이 실패하면 작업 화면과 watch 출력에 어떤 모듈이 없는지
표시된다. 필요하면 Python에 RacePlan을 설치해서 쓴다(README의 설치 절차).

Inspector의 "다시 실행" 명령(`raceplan-run …`)은 Python 설치판용이다. exe에서는 그 위에 "Python 설치판용 명령 · exe에는 없음"이 보인다.

## 제한

- 검증한 환경: Windows 11 x64. Windows 10·ARM64는 확인 전이다. 깨끗한 Windows(Sandbox·새 VM)에서의 확인은 아직 없다
  (아래 검증표 1은 흉내다).
- 플래너가 만든 하위 프로세스까지 실행마다 Windows Job Object로 묶어, 취소·시간 초과·종료 시, 그리고 실행이 정상으로 끝난
  뒤에도 남은 것을 함께 멈춘다. 프로그램이 강제 종료(작업 관리자 등)되면 하위 프로세스는 멈추지만 그 실행의
  `workflow.json`은 `running`으로 남을 수 있다. 콘솔 창 닫기는 처리하지만, 로그오프·Windows 종료 때 콘솔 프로그램에
  알림이 오는 것은 Windows가 보장하지 않는다.
- exe는 RacePlan 연구 패키지의 봉인 재현 환경이 아니다. 봉인 재현은 당시 저장소 체크아웃에서 한다.
- 결과 폴더의 저장 기록은 당시 지도 파일의 절대 경로를 가리킨다. 배포 폴더를 옮기거나 새 버전으로 바꾸면 예전 실행의
  지도를 다시 열지 못할 수 있다(당시 폴더를 남겨 두면 열린다).
- RacePlan 자체의 라이선스 고지 파일은 아직 없다(`pyproject.toml`에 MIT로 선언). 저장소에 `LICENSE`가 생기면 빌드가 함께 넣는다.

## 빌드 (개발자)

저장소 루트, Windows x64에서:

```powershell
uv sync --locked --python 3.13 --extra dev --extra exe
uv run --locked --python 3.13 --extra exe python packaging/windows/build.py
```

`dist/RacePlan/`과 `dist/RacePlan-<버전>-windows-x64.zip`(+ `.sha256`)이 생긴다. 빌드는 CPython 3.13 64비트·Windows x64가
아니면 시작하지 않고, exe 안의 RacePlan `.py` 파일이 저장소와 바이트 단위로 같은지 확인해 다르면 실패한다(실험·분석 기록이
소스 해시를 남기기 때문). 라이선스 고지가 없으면 실패한다. 고정: PyInstaller 6.22.3, `uv.lock`. zip의 바이트 단위
재현성은 보장하지 않는다. `BUILD-INFO.txt`에 커밋(미커밋 변경 여부 포함)과 버전이 남는다.

## 릴리스 검증표

각 항목을 새로 만든 zip으로 확인하고 결과를 기록한다.

1. **깨끗한 환경 흉내**: 새 PowerShell에서 exe 경로를 변수에 둔 뒤 관계없는 폴더로 이동하고, 그 셸에서만
   `$env:PATH = "$env:SystemRoot\System32"`, `Remove-Item Env:PYTHONPATH, Env:PYTHONHOME -ErrorAction SilentlyContinue`.
   절대 경로로 GUI와 `watch --once`를 실행한다. (설치된 Python을 지우는 것은 아니므로 Windows Sandbox·새 VM 확인을 대신하지 않는다.)
2. **첫 비교**: 더블클릭 → 브라우저 → `+ 새 실행` → demo + astar + 공백·한글 경로에 복사한 예제 플래너 → 완료 → 새 결과가
   열리고 지도·궤적 재생, `workflow.json` complete, CSV·PNG 생성.
3. **watch**: 브라우저와 `RacePlan.exe watch` 양쪽. 저장 → 재실행·새 결과, 실행 중 저장 → 이전 실행 취소, 끄기 뒤 저장 → 실행 없음.
   `--once` 성공 0, 깨진 플래너 1.
4. **오류·종료**: 없는 모듈 import 안내, 잘못된 경로, `--no-browser`, 토큰 없는 탭은 읽기 전용. 느린 플래너 실행 중
   취소·시간 초과·`Ctrl+C`·콘솔 창 닫기 → 프로세스 잔류 없음, 해당 실행은 failed(Cancelled/Timeout).
5. **소스 동일성**: 빌드 출력의 "RacePlan sources checked" 줄. 같은 커밋의 Python 설치판과 exe에서 demo를 실행해
   `comparison_manifest.json`과 `analysis/analysis.json`의 `source_sha256`이 같은지 비교.

### 기록: 0.1.0 첫 빌드 (2026-11-20, Windows 11 x64, 개발 PC)

| 항목 | 결과 |
|---|---|
| 빌드 | 약 1분, 폴더 62.8 MiB, zip 27.2 MiB, RacePlan 소스 54개 바이트 동일 |
| 1 깨끗한 환경 흉내 | PATH=System32, PYTHON* 제거, 무관한 폴더에서 `watch --once`: 성공 0, 없는 모듈(scipy) 1 + 안내, 공백·한글 경로 정상 |
| 2 첫 비교 | exe GUI(`--no-browser`)에서 `+ 새 실행` → 완료·새 결과 열림, 재생·Inspector 정상, frozen 안내 |
| 3 watch | 브라우저 watch: 저장 → 다음 실행이 열림, watch 끄기. CLI `--once` 0/1 |
| 4 종료 | 느린 플래너 실행 중 콘솔 창 닫기(WM_CLOSE) → 0.1초 안에 서버·워커 종료, 실행 기록 failed/Cancelled |
| 5 소스 동일성 | 개발 설치와 exe의 demo 실행: `source_sha256` 54/54, 2/2 동일, episodes 수치 동일 |
| 미확인 | Windows Sandbox·새 VM, 실제 더블클릭 시 SmartScreen, Windows Terminal 탭 닫기, 읽기 전용 설치 폴더 |
