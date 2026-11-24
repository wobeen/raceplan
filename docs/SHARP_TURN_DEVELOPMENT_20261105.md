# 급회전 제곱 비용 개발 비교 — 2026-11-05

## 질문과 범위

기존 방향-state A*는 총 절대 회전량을 줄였지만 최대 이산 곡률과 충돌을 개선하지
못했다. 한 번의 90도 회전과 두 번의 45도 회전은 절대 회전량 합이 같다는 한계를
분리하기 위해 `examples/sharp_turn_planner.py`에 제곱 회전 비용을 추가했다.

```text
step_length + absolute_weight × |heading_change|
            + squared_weight × heading_change²
```

과거 봉인 후보와 실행 기록은 수정하지 않았다. 이 비교는 이미 공개된
`turn_aware_holdout_20261103`의 **validation 입력만** 사용한 개발 선택이며,
evaluation 입력은 읽거나 실행하지 않았다. A*와 제곱 가중치 0.10/0.20/0.40,
절대0.05+제곱0.20의 네 변형을 2 family × 2 query × 3 seed로 비교해 총60 episode를
한 번 실행했다. 선택 규칙은 먼저 A* 대비 도달률 회귀가 없어야 하고, 그다음 성공
RMSE와 최대 이산 곡률을 비교하는 것이었다.

## 결과

| planner | 도달/12 | 충돌 | 성공 RMSE 중앙값(m) | 성공 시간 중앙값(s) | 최대 이산 곡률 중앙값(/m) |
|---|---:|---:|---:|---:|---:|
| A* | 6 | 6 | 0.07968 | 11.20 | 7.7805 |
| 제곱0.10 | 3 | 9 | 0.03048 | 11.85 | 7.5890 |
| 제곱0.20 | 0 | 12 | n/a | n/a | 7.5890 |
| 제곱0.40 | 3 | 9 | 0.03165 | 11.85 | 7.6338 |
| 절대0.05+제곱0.20 | 3 | 9 | 0.03048 | 11.85 | 7.6338 |

제곱0.10과 결합 후보는 A*와 함께 성공한3쌍에서 RMSE가 중앙값0.04882m 낮았지만
완료시간은0.65s 길었다. 동시에 A*가 성공한3쌍을 잃었고 새 성공은 없었다.
모든 제곱 비용 후보의 전체 주행 clearance 중앙값은0m였다. 총 절대 회전량은
12.5664→약1.9635rad로 크게 줄었지만 최대 이산 곡률은 약2.5% 감소에 그쳤다.
방향 변화 횟수 비용을 줄이는 것과 연속 곡률·차량 여유를 만드는 것은 같지 않았다.

## 판단

네 후보 모두 사전 선택 규칙의 첫 조건인 “도달률 무회귀”를 통과하지 못했다.
따라서 후보를 선택하지 않고 새 held-out 평가도 실행하지 않는다. 이 음성 결과는
point-grid의 비용항만 바꾸어 고정 controller의 추종 가능한 곡률을 만드는 접근의
구조적 한계를 강화한다. 다음 연구 후보는 비용 가중치 추가가 아니라 Hybrid A*처럼
조향 가능한 motion primitive를 쓰거나, 충돌 검사를 포함한 곡률 연속 후처리를 별도
가설로 정의해야 한다.

재현 명령과 공유 집계는 다음과 같다. 원본 trajectory/batch는 ignore된
`results/raw/sharp_turn_development_20261105/`, 집계와 protocol은
`results/analysis/sharp_turn_development_20261105/`에 보존한다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe results/sharp_turn_development.py `
  --output-dir results/raw/sharp_turn_development_20261105
```
