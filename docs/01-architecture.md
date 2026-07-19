# 아키텍처 설계

대상: Hermes Agent `kind: platform` 플러그인, 플랫폼 이름 `kakaotalk`.
전제 지식은 [00-hermes-plugin-sdk.md](00-hermes-plugin-sdk.md)에 있습니다.

## 1. 핵심 설계 결정

### D1. 인바운드 트랜스포트 — 릴레이 우선, 직접 웹훅은 뒤에

카카오톡 채널의 스킬 서버는 **공개 HTTPS 엔드포인트**를 요구합니다. 반면 Hermes
게이트웨이는 보통 개인 머신/홈서버에서 돕니다. 두 가지 경로가 있습니다.

| | A. 릴레이 클라이언트 | B. 직접 웹훅 서버 |
|---|---|---|
| 인바운드 | 릴레이에 SSE 구독 | 플러그인이 aiohttp 서버 기동 |
| 공개 IP/터널 | 불필요 | 필수 (도메인 + TLS) |
| 카카오 5초 ACK | 릴레이가 흡수 | 직접 처리해야 함 |
| 서명 검증 | 릴레이 담당 | 플러그인 담당 |
| 신뢰 경계 | 제3자 릴레이가 평문 메시지를 봄 | 없음 |
| OpenClaw 자산 재사용 | 높음 (검증된 와이어 프로토콜) | 낮음 |

**권장: A를 v0.1로, B를 v0.2로. 단, 처음부터 `KakaoTransport` 프로토콜 뒤에
두 구현을 넣어 어댑터가 어느 쪽인지 모르게 한다.** A는 즉시 동작하는 경로를 주고,
B는 릴레이 의존성을 제거하는 출구를 남깁니다. OpenClaw 플러그인이 릴레이에
묶여 있는 것은 알려진 부채이며(`docs/RELAY_DEPENDENCY_MAP.md`), 같은 부채를
설계 단계에서 반복할 이유가 없습니다.

> 열린 질문 Q1: 릴레이(`k.tess.dev`)를 그대로 쓸지, 포크할지, 자체 호스팅할지.
> OpenClaw 저장소의 `docs/RELAY_SELF_HOSTING.md`를 먼저 검토해야 합니다.
> 또한 **릴레이 와이어 스펙 문서(`docs/relay-server-api-spec.md`)가 OpenClaw
> 저장소에 실제로는 없습니다** — 코드에서 역으로 문서화해야 합니다.

### D2. 다중 계정은 v1 범위에서 뺀다

Hermes의 `GatewayConfig.platforms`는 플랫폼당 `PlatformConfig` 하나입니다.
OpenClaw의 `accounts.<id>` 모델을 억지로 얹으면 코어와 싸우게 됩니다.
**단일 카카오 채널 = 단일 Hermes 프로필**을 기본으로 하고, 다중 채널이 필요하면
Hermes 프로필 분리로 해결합니다.

### D3. 접근 제어는 Hermes 것을 쓴다

OpenClaw의 `dmPolicy`(`pairing|allowlist|open|disabled`)와 자체 페어링 코드
로직은 **이식하지 않습니다.** Hermes의 `unauthorized_dm_behavior="pair"` +
`gateway/pairing.py`가 기능적으로 상위 집합입니다(TTL, 레이트리밋, 잠금,
`chmod 0600`, 코드 미로깅). 우리는 `allowed_users_env`/`allow_all_env`만
등록하면 됩니다.

### D4. 카카오 도메인 계층은 호스트를 몰라야 한다

OpenClaw 버전에서 `src/kakao/**`가 호스트 import 0개였던 것이 이식을 가능하게
만든 유일한 이유입니다. Python 판에서도 **`kakao/` 패키지는 Hermes를 import하지
않는다**를 불변식으로 고정하고 테스트로 강제합니다.

### D5. 명령어 하이재킹은 하지 않는다

OpenClaw `gateway.ts`는 `/help /github /about /relay /session /card` 등을
호스트 디스패치 **이전에** 가로채 직접 응답합니다(997줄 단일 파일의 주범).
Hermes에는 `ctx.register_command()`가 있으므로 슬래시 명령은 그쪽에 등록하고,
어댑터는 순수 트랜스포트로 유지합니다.

## 2. 모듈 구조

```
hermes-kakao-talkchannel-plugin/
  plugin.yaml                 # kind: platform, requires_env / optional_env
  __init__.py                 # register(ctx) → ctx.register_platform(...)
  adapter.py                  # KakaoAdapter(BasePlatformAdapter) — 3개 추상 메서드
  registration.py             # check_fn / validate_config / is_connected
                              # env_enablement_fn / apply_yaml_config_fn / setup_fn
  commands.py                 # ctx.register_command 기반 /card 등
  config.py                   # KakaoConfig 데이터클래스, env>YAML 병합
  kakao/                      # ★ 순수 도메인 — Hermes import 금지
    __init__.py
    payload.py                # 오픈빌더 SkillPayload 파싱
    response.py               # simpleText / textCard / carousel 빌더
    limits.py                 # KAKAO_LIMITS (outputs 3, quickReplies 10, 길이)
    markdown.py               # strip_markdown — 카카오는 마크다운 미지원
    chunking.py               # chunk_text_for_kakao
  transport/
    __init__.py               # KakaoTransport 프로토콜 (Protocol)
    relay.py                  # A안: SSE 구독 + POST reply
    webhook.py                # B안: aiohttp 스킬 서버 + HMAC 검증 (v0.2)
    models.py                 # InboundMessage 등 트랜스포트 DTO
  tests/
    test_adapter.py test_registration.py test_config.py
    kakao/test_payload.py test_response.py test_limits.py test_chunking.py
    transport/test_relay.py
    fixtures/payloads.py
```

## 3. 인바운드 경로

```
카카오톡 사용자
   │
   ▼ 오픈빌더 스킬 콜백 (~5초 데드라인)
릴레이 서버 ─── 즉시 200 ACK ──▶ 카카오
   │  (SSE: message / ping / error / pairing_*)
   ▼
transport/relay.py  ── InboundMessage ──▶ adapter.py
                                              │ kakao/payload.py 로 정규화
                                              ▼
                                    self.build_source(...)  → SessionSource
                                    MessageEvent(...)
                                              ▼
                                    await self.handle_message(event)
                                              ▼
                          Hermes 코어 (세션 키: agent:main:kakaotalk:dm:{userId})
```

`build_source`에 넘길 값:

| 인자 | 값 |
|---|---|
| `chat_id` | 카카오 `userRequest.user.id` |
| `chat_type` | `"dm"` (카카오 채널은 1:1만) |
| `user_id` | 동일 |
| `user_name` | 동일 (카카오는 표시명 미제공) |
| `chat_name` | 채널 ID |

결과 세션 키: `agent:main:kakaotalk:dm:{userId}`.
OpenClaw가 손으로 만들던 `SessionKey` 문자열과 **형식이 같습니다** — 우연이
아니라 두 호스트가 같은 관례를 쓰기 때문이고, 세션 이력 이관 가능성을 남깁니다.

## 4. 아웃바운드 경로

```
Hermes 코어 응답 텍스트
   ▼
adapter.send(chat_id, content, reply_to, metadata) -> SendResult
   │  1. kakao/markdown.py  → 마크다운 제거
   │  2. 청킹은 하지 않음 — 레지스트리 max_message_length가 중앙 처리
   │  3. metadata에 채널 카드 지시가 있으면 kakao/response.py 로 카드 빌드
   │  4. kakao/limits.py 로 outputs≤3 / quickReplies≤10 강제
   ▼
transport → 릴레이 POST reply (또는 카카오 push API)
   ▼ SendResult(success=..., message_id=..., retryable=..., error_kind=...)
```

주의:

- `max_message_length`는 **UTF-16이 아니라 카카오 기준 문자 수**입니다.
  LINE처럼 `message_len_fn` 오버라이드가 필요한지 확인 필요 (열린 질문 Q2).
- 카카오는 마크다운을 렌더링하지 않습니다. LINE 어댑터가 같은 문제를 어떻게
  처리하는지가 그대로 참고가 됩니다.
- `_SYSTEM_BYPASS_PREFIXES`(`⚡ Interrupting`, `⏳ Queued`, `⏩ Steered`, `💾`)는
  어떤 변환/캐싱을 얹어도 그대로 보여야 합니다.

## 5. 응답 지연 UX (카카오 특유)

에이전트 세션은 3~30분, 카카오 콜백 창은 ~5초. LINE 어댑터가 쓰는 패턴을
그대로 차용합니다:

1. 콜백 즉시 ACK + "생각 중" 플레이스홀더 응답.
2. 에이전트 완료 시 push/reply 경로로 실제 응답 전달.
3. 일정 시간(예: 45초) 경과 시 "계속 보기" 퀵리플라이/포스트백을 쏴서
   사용자 액션으로 무료 응답 창을 재개.

`_keep_typing` 오버라이드가 3번의 자리이며, `send`는 `PENDING → READY →
DELIVERED/ERROR` 상태 기계를 통과합니다. **설계를 확정하기 전에
`plugins/platforms/line/adapter.py`(1654줄)를 통독해야 합니다.**

## 6. 설정 표면

`plugin.yaml`:

- `requires_env`: `KAKAO_RELAY_URL`(기본값 있음), `KAKAO_RELAY_TOKEN`
  (B안에서는 `KAKAO_CHANNEL_ID`, `KAKAO_BOT_SECRET`)
- `optional_env`: `KAKAO_ALLOWED_USERS`, `KAKAO_ALLOW_ALL_USERS`,
  `KAKAO_HOME_CHANNEL`, `KAKAO_RESPONSE_PREFIX`

`config.yaml`:

```yaml
gateway:
  platforms:
    kakaotalk:
      enabled: true
      extra:
        transport: relay          # relay | webhook
        relay_url: https://k.tess.dev/
        response_prefix: ""
        chunk_mode: length
```

`env_enablement_fn`이 어댑터 생성 전에 `extra`를 채워 `hermes status`가 SDK
인스턴스화 없이 동작하게 합니다.

## 7. 불변식 (테스트로 강제)

1. `kakao/**`는 `hermes*`를 import하지 않는다.
2. `register()`는 무거운 HTTP/카카오 SDK를 최상단에서 import하지 않는다
   (지연 로딩 요구사항).
3. `plugin.yaml`의 `kind`는 반드시 `platform` — 오타 시 조용히 격하됨.
4. `ctx.register_platform`에 넘기는 키는 전부 `PlatformEntry` 필드
   (알 수 없는 키는 `TypeError`).
5. 아웃바운드는 항상 outputs ≤ 3, quickReplies ≤ 10.
