# seed 지도 생성 (raceplan.seed_maps)

seed 하나가 지도 하나를 뜻합니다. 같은 종류·값·revision·seed면 OS·Python과 관계없이 **바이트까지 같은** 지도와
시나리오가 나옵니다(Windows·Ubuntu CI에서 고정 해시로 확인). 연구용 지도군(흩어진 섬, 엇갈린 벽과 창, 좁은 통로)을
seed 범위로 늘려 planner를 더 많은 지도에서 비교하려고 만들었습니다.

## 종류와 값

모든 값은 칸(1칸 = 0.1 m) 단위 정수입니다. 괄호는 기본값과 허용 범위입니다. 바깥 테두리 1칸은 항상 벽입니다.

| 종류 | 모양 | 값 |
|---|---|---|
| `offset_islands` 흩어진 섬 | 양 끝 2 m를 뺀 가로를 섬 수로 나눈 구간마다 섬 하나, 가운데 아래·위를 번갈아 | width 104 (64–128), height 72 (40–96), islands 2 (2–4), block_w 8 (4–10), block_h 12 (4–16) |
| `staggered_windows` 엇갈린 벽과 창 | 벽 2개(가로 1/3·2/3), 창 하나씩, 아래→위 또는 위→아래 | width 104, height 72, wall_w 6 (2–8), window_h 20 (12–28), offset 8 (4–18), jitter 3 (0–4) |
| `gate` 좁은 통로 | 가운데 판 하나, 가운데 구멍 폭을 seed가 고름 | width 80 (64–128), height 41 (40–96), wall_w 20 (4–28), gap_min 5, gap_max 13 (홀수 3–21) |

출발·도착: 섬·창은 왼쪽 끝과 오른쪽 끝에서 0.75 m, 높이는 seed가 지도 가운데 절반에서 고릅니다. gate는 가운데 높이에서
양 끝 1.05 m. 방향은 모두 +x입니다. 값이 지도에 들어가지 않는 조합(예: 창이 지도 밖으로 나감, gate 판이 출발점에
닿음)은 seed를 쓰기 전에 거부합니다.

## 무작위 규칙 (revision 1)

지도마다 새 `PCG64(seed)`, 뽑을 때마다 64비트 원시 값 하나를 `lo + ((word × (hi − lo + 1)) >> 64)`로 [lo, hi]에 옮깁니다.
부동소수 난수나 NumPy의 표본 함수(알고리즘이 바뀔 수 있음)는 쓰지 않습니다. 좌표는 정수 mm에서 씁니다. 이 규칙이나
배치가 바뀌면 revision을 올리고, 예전 revision은 거부합니다(같은 이름이 다른 지도를 가리키지 않게).

## 받아들이는 기준

기본 차량(축거 0.33 m, 길이 0.58 m, 폭 0.31 m)이 지나갈 길이 있다는 **보수적인 증거**가 있어야 지도를 남깁니다.

- 섬·창: 출발 칸에서 +x 방향으로 시작해 도착 칸에 **+x 방향으로**(q0.yaml의 자세 그대로) 닿는 길을, 1칸 전진과 반지름
  0.7 m(최소 회전 반경 0.68 m보다 큼) 90° 호로 이루어진 격자에서 BFS로 찾습니다. 각 동작이 쓸고 가는 상자를
  0.5 m(뒤축에서 차체 끝까지 0.42 m보다 큼) 넓혀 검사합니다. 섬을 양 끝 2 m 밖에 두는 것은 출발·도착 방향으로 줄을
  맞출 자리를 남기기 위해서입니다(기본값과 여러 값 조합에서 seed 200개 모두 통과).
- gate: 차체 상자(뒤축 기준 뒤 0.19 m·앞 0.39 m·반폭 0.155 m)를 출발에서 도착까지 곧게 쓸어 봅니다. 0.3 m 통로는
  차 폭보다 좁아 거부되고 0.5 m는 통과합니다.

증거가 없는 seed는 사유(`endpoint_blocked`, `no_motion_witness`, `gate_clearance`)와 함께 **거부로 기록**하고 다른 지도로
다시 뽑지 않습니다. 증거는 길이 있다는 뜻일 뿐, planner가 찾거나 추종기가 따라간다는 뜻은 아닙니다.

실측(seed 1–6, 노이즈 0, A* / Hybrid A* 도달): 섬 6/6 · 6/6, gate 6/6 · 6/6, 엇갈린 창 0/6 · 2/6. 0.1 m 격자의 A*는 창
모서리에 붙은 경로를 내고 추종기가 모서리를 깎아 충돌합니다. 이것은 생성기 결함이 아니라 비교하려는 차이입니다. 창의
offset 12(설계 초안)는 A* 0/6 · Hybrid A* 1/6이라 기본값을 연구 지도의 엇갈림(약 0.85 m)에 가까운 8로 정했습니다.

## 만들어지는 폴더

```
<출력 폴더>/
  family.json            종류·값·revision·seed 범위·규칙·각 지도의 상태와 파일 sha256 (마지막에 원자적으로 씀)
  suite.yaml             모든 seed가 받아들여졌을 때만: raceplan-suite에 그대로 넣는 설정
  members/<이름>/        map.pgm(P5, 맨 윗줄부터) · map.yaml · q0.yaml(map_seed = seed) · geometry.json
```

이름은 `<종류>-r<revision>-p<값 sha256 앞 16자>-s<seed 10자리>`입니다. 거부된 seed는 파일 없이 family.json에 사유만
남습니다(같은 값으로 언제든 다시 만들어 볼 수 있음). 출력 폴더가 이미 있으면 거부합니다(덮어쓰지 않음).

## 명령

```powershell
.\.venv\Scripts\raceplan-generate.exe create gate --seeds 11:18 --output-dir generated/gates
.\.venv\Scripts\raceplan-generate.exe create staggered_windows --seeds 0:9 --param offset=6 --param jitter=2 --output-dir generated/windows
.\.venv\Scripts\raceplan-generate.exe verify generated/gates
.\.venv\Scripts\raceplan-suite.exe generated/gates/suite.yaml --output-dir results/raw/gates
```

exe 배포판은 `RacePlan.exe generate create …` / `RacePlan.exe generate verify …`입니다. 한 번에 seed 256개까지.
종료 코드: 0 모두 통과(또는 verify 일치), 3 거부된 seed가 있음(폴더는 남고 suite.yaml 없음), 2 인자 오류, 1 입출력 오류나
verify 불일치. `verify`는 family.json의 값으로 모든 지도를 다시 만들어 파일을 바이트 단위로 비교하고, 바뀐·빠진·더 있는
파일을 알려 줍니다.

## 탐색기에서

`+ 새 실행` → 지도 "seed로 지도 생성" → 종류·지도 seed 범위(최대 16개)·값을 고르고 실행합니다. 서버가 결과 폴더의
`generated/<시각-종류-seed범위-토큰>/`에 지도를 만들고, 모두 받아들여지면 곧바로 suite로 실행해 "전체 N case" 보기로
엽니다. 거부된 seed가 하나라도 있으면 아무것도 실행하지 않고 그 seed와 사유, 보관 위치를 보여 줍니다(HTTP 422).
주행 seed·노이즈·planner는 기존 시나리오와 같은 방식이고, watch는 생성 지도에 쓸 수 없습니다.

서버는 결과 폴더 아래 `generated/`·`gui-runs/`·`gui-runs/.suite-inputs/`가 링크나 junction이면 쓰기 전에 거부합니다(각 단계
항목 자체를 검사). 검사와 쓰기 사이에 다른 프로세스가 폴더를 junction으로 바꿔치기하는 경쟁은 막지 않습니다. 그런 프로세스는
이미 같은 사용자 권한으로 어디에나 쓸 수 있어 막아도 지켜지는 것이 없고, 막으려면 Windows에서 링크를 따르지 않는 디렉터리
핸들로 모든 쓰기를 해야 해서 받아들인 위험으로 남깁니다(검증 3차 지적).
