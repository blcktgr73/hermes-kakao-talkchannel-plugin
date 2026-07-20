# 알려진 릴레이 클라이언트 결함 (as-is 이식)

이 플러그인은 `openclaw-kakao-talkchannel-plugin`의 릴레이 클라이언트를 **동작
호환(as-is)** 으로 이식했습니다. OpenClaw 판에서 이 결함들을 고치려 시도했을 때
동작하지 않았던 이력이 있어, 검증 없이 고치는 대신 그대로 옮기고 여기에
기록합니다.

코드에서는 `AS-IS (D<n>)` 주석으로 표시되어 있고, 각 항목은 테스트로 현재 동작이
고정되어 있습니다. 고칠 때는 테스트도 함께 바꿔야 합니다.

**2026-07-20 갱신.** 실기 검증으로 근거가 생긴 것들은 고쳤습니다. 관측이 필요한
항목만 as-is로 남아 있습니다.

| ID | 이슈 | 요약 | 상태 |
|---|---|---|---|
| D1 | [#1](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/1) | `/health`만 정규화를 안 해 `//health` 요청 | **수정** — 릴레이가 `r.Get("/health")`로 등록하고, 수정 후 `probe ok` 85ms 실증 |
| D2 | [#2](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/2) | 300초 타임아웃이 정상 연결도 끊음 | **도달 불가** — 릴레이가 60초에 먼저 끊습니다 |
| D3 | [#3](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/3) | 지터가 상한 적용 *후* 더해져 최대 20% 초과 | **수정** — 순수 클라이언트 계산이라 관측 불필요 |
| D4 | [#4](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/4) | `ping` 미처리, 유휴 워치독 없음 | **실익 없음** — 릴레이의 60초 종료가 죽은 연결을 대신 감지 |
| D5 | [#5](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/5) | 멀티라인 `data:` 중 마지막 줄만 사용 | **수정** — 명세대로 이어붙임 |
| D6 | [#6](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/6) | 세션 호출에 타임아웃 없음 | **수정** — 10초 + 토큰 URL 인코딩 |
| D7 | [#7](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/7) | 응답 경로에 `openclaw` 하드코딩 | **명명 문제** — 기능 영향 없음, 릴레이 별칭 선행 |

[#8 엔드투엔드 검증](https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin/issues/8)은
2026-07-20 완료. **이슈는 모두 닫혔습니다.**

### D5에 대한 판단 정정

"관측 없이 고치면 순수 리스크"라고 적었던 것은 틀렸습니다. `data:` 줄을 이어붙이는
것은 **줄이 하나뿐일 때 no-op**이라, 릴레이가 단일 라인만 보내도 위험이 없습니다.
명세 자체가 근거이므로 관측을 기다릴 이유가 없었습니다. 신중함을 잘못 계산한 사례로
남깁니다.

### D2 / D4가 다시 살아나는 조건

릴레이의 `chimiddleware.Timeout(60s)`가 제거되면 **둘 다 즉시 실제 문제가 됩니다.**
그 변경은 `kakao-talkchannel-relay-openclaw`의 `cmd/server/main.go`에 미커밋 상태로
있습니다. 그것을 배포한다면 이 두 항목을 같은 작업에서 함께 다뤄야 합니다 — 지금은
릴레이의 60초 재활용이 연결 수명 관리를 대신하고 있습니다.

### 이식 당시 없던, 실기에서 드러난 결함

as-is 이식 목록에는 없었지만 실제로 가장 큰 피해를 준 것입니다.

**SSE 정상 종료 후 백오프 없는 재연결.** 서버가 즉시 닫으면 재연결 루프가 됩니다.
릴레이가 subscribe마다 `queued`를 재flush하므로, **인바운드 1건이 94번 재전송되어
94개 에이전트 턴이 시작**됐습니다. TS 원본에도 같은 구멍이 있습니다.
→ 수정: 정상 종료 재연결에 지연 + 이미 처리한 메시지 id 무시.

---

## D1 — `health_check`의 이중 슬래시

`send_reply`, `connect_sse`, `create_session`, `check_session_status`는 모두 베이스
URL을 정규화(`endsWith("/") ? url : url + "/"`)하지만 `health_check`만 하지
않습니다.

```python
url = f"{config.relay_url}/health"   # 정규화 없음
```

기본 릴레이 URL이 `https://k.tess.dev/`(슬래시로 끝남)이므로 실제 요청은
`https://k.tess.dev//health`가 됩니다.

- **위험도**: 낮음. 대부분의 HTTP 서버/라우터는 `//health`를 `/health`로 취급합니다.
- **고칠 때 주의**: 릴레이가 `//health`에만 응답하도록 라우팅되어 있을 가능성은
  낮지만, 고치기 전에 두 경로를 모두 curl로 찍어보는 것이 안전합니다.
- **현재 고정 테스트**: `tests/transport/test_client.py::test_health_check_produces_a_double_slash_url`

가장 먼저 확인해볼 항목입니다.

## D2 — 300초 연결 타임아웃

`connect_sse`는 연결 시도마다 `timeout_ms`(기본 300000)를 겁니다. 이것은 유휴
타임아웃이 아니라 **전체 연결 수명**에 걸리는 값이라, 릴레이가 정상적으로 ping을
보내고 있어도 5분마다 연결이 끊기고 백오프를 거쳐 재접속합니다.

`start_relay_stream`은 `timeout_ms`를 넘기지 않으므로 항상 기본값 300초가 적용됩니다.

- **영향**: 5분마다 강제 재접속. 릴레이 ping 주기가 짧으면 사실상 재접속 트레드밀.
- **올바른 수정**: `aiohttp.ClientTimeout(sock_read=...)` 기반 유휴 타임아웃 +
  ping 수신 시각을 갱신하는 워치독(D4와 함께).

## D3 — 지터가 상한을 초과

```python
capped_delay = min(exponential_delay, max_delay_ms)
jitter = capped_delay * 0.2 * random.random()
return math.floor(capped_delay + jitter)
```

지터를 상한 적용 **후** 더하므로 반환값이 `max_delay_ms`를 최대 20% 넘습니다
(상한 30000 → 최대 35999).

- **영향**: 낮음. 재접속이 아주 약간 느려질 뿐입니다.
- **수정**: `min(exponential + jitter, max_delay_ms)` 또는 지터를 감산 방향으로.
- **현재 고정 테스트**: `tests/transport/test_sse.py::test_backoff_can_exceed_the_cap_by_up_to_twenty_percent`

## D4 — `ping` 미처리, 워치독 없음

SSE 이벤트 타입 `ping`에 대응하는 분기가 없습니다. 클라이언트측 유휴 감시도
없어서, TCP 연결이 조용히 죽으면 D2의 300초 타임아웃에 걸릴 때까지 감지되지
않습니다.

- **영향**: 최악의 경우 메시지 유실 없이 최대 5분간 먹통.
- **수정**: `ping` 수신 시각을 기록하고 N초간 ping이 없으면 능동 재접속. D2와 한
  세트로 고쳐야 의미가 있습니다.

## D5 — 멀티라인 `data:` 잘림

SSE 명세는 한 이벤트 블록의 여러 `data:` 줄을 개행으로 이어붙이라고 규정하지만,
파서는 마지막 줄로 덮어씁니다.

```python
elif line.startswith("data:"):
    data_line = line[5:].strip()   # 마지막 줄이 이김
```

- **영향**: **미지.** 릴레이가 실제로 멀티라인 `data:`를 보내는지 확인되지
  않았습니다. 보내지 않는다면 무해하고, 보낸다면 긴 메시지가 조용히 깨집니다.
- **확인 방법**: 릴레이 스트림을 `curl -N`으로 직접 받아 관찰.
- **현재 고정 테스트**: `tests/transport/test_sse.py::test_multiline_data_keeps_only_the_last_line`

## D6 — 타임아웃 없는 호출

`create_session`, `check_session_status`, `send_callback`은 원본이 타임아웃을 걸지
않았고, 이식본도 그대로입니다. 다만 Python `aiohttp`는 세션 기본 총 타임아웃이
5분이라, JS `fetch`의 무제한과 달리 최소한의 상한은 존재합니다.

- **수정**: 각각 명시적 `ClientTimeout` 부여. 상대적으로 안전한 수정입니다.

## D7 — `openclaw` 하드코딩 경로

응답 전송 엔드포인트가 `POST {relay}openclaw/reply`입니다. 호스트 중립적인 이름이
아니지만, 릴레이가 그 경로만 제공하므로 그대로 씁니다.

- **수정**: 릴레이에 호스트 중립 별칭(`/v1/reply` 등) 추가 요청.

---

## 고치기 전 체크리스트

as-is 결정의 이유가 "고치려다 동작이 깨졌다"이므로, 순서를 지키는 것이 중요합니다.

1. 릴레이 와이어 동작을 **먼저 관측**합니다 (`curl -N`으로 SSE 원본 확인,
   `/health`와 `//health` 양쪽 응답 확인).
2. 관측 결과를 `docs/relay-wire-protocol.md`에 기록합니다.
3. 관측이 뒷받침하는 항목만 고칩니다. D1 → D6 → D3 순이 위험도가 낮습니다.
4. D2와 D4는 반드시 함께 고칩니다. 하나만 고치면 연결 수명 관리가 무너집니다.
5. D5는 릴레이가 멀티라인을 보낸다는 증거가 나오기 전까지 건드리지 않습니다.
