# OpenClaw → Hermes 이식 대응표

원본: `C:\Users\blckt\prj\openclaw-kakao-talkchannel-plugin` (TypeScript, OpenClaw)
대상: 본 저장소 (Python 3.11+, Hermes Agent)

## 1. 한눈에 보기

| 계층 | 원본 | 이식 난이도 | 처리 |
|---|---|---|---|
| 카카오 순수 도메인 | `src/kakao/**` | 낮음 | TS→Python 기계적 번역 |
| 타입/스키마 | `src/types.ts`, `src/config/schema.ts` | 낮음 | Zod → dataclass + 수동 검증 |
| 릴레이 트랜스포트 | `src/relay/{client,sse,session}.ts` | 중간 | aiohttp/httpx로 재작성 |
| 세션 토큰 저장 | `src/relay/session-store.ts` | 중간 | 호스트 결합 — 재설계 |
| 호스트 어댑터 | `src/adapters/**` | **높음** | **전면 재작성** |
| 진입점/채널 기술자 | `index.ts`, `src/channel.ts` | 높음 | 전면 재작성 |
| 런타임 싱글턴 | `src/runtime.ts` | — | **삭제** |

## 2. 파일 단위 대응

### 그대로 옮기는 것 (호스트 무관)

| OpenClaw | Hermes | 비고 |
|---|---|---|
| `src/kakao/payload.ts` | `kakao/payload.py` | 오픈빌더 SkillPayload 파싱 |
| `src/kakao/response.ts` | `kakao/response.py` | `buildSimpleTextResponse` 등 빌더 전체 |
| `src/kakao/limits.ts` | `kakao/limits.py` | `KAKAO_LIMITS` 상수 |
| `src/kakao/callback.ts` | `kakao/payload.py`에 병합 | |
| — (`response.ts` 내부) | `kakao/markdown.py` | `stripMarkdown` 분리 |
| — (`response.ts` 내부) | `kakao/chunking.py` | `chunkTextForKakao` 분리 |
| `tests/fixtures/payloads.ts` | `tests/fixtures/payloads.py` | 픽스처 그대로 |

### 재작성하는 것

| OpenClaw | Hermes | 이유 |
|---|---|---|
| `src/relay/client.ts` | `transport/relay.py` | fetch → httpx/aiohttp |
| `src/relay/sse.ts` | `transport/relay.py` | SSE 재접속/`Last-Event-ID` 로직 유지 |
| `src/relay/session.ts` | `transport/relay.py` | 세션 생성/상태 조회 |
| `src/relay/stream.ts` | `transport/relay.py` | 토큰 해결 순서만 보존 |
| `src/config/schema.ts` | `config.py` | Zod → dataclass |
| `src/types.ts` | `transport/models.py` + `kakao/` | 448줄을 소유 계층별로 분할 |

### 버리는 것

| OpenClaw | 버리는 이유 |
|---|---|
| `src/runtime.ts` | 모듈 전역 싱글턴. Hermes는 어댑터 인스턴스에 config를 주입 |
| `src/openclaw.d.ts` | OpenClaw 전용 ambient 선언 (실제 SDK 타입을 가려서 컴파일러 검증을 무력화하던 것) |
| `src/adapters/pairing.ts` | Hermes `gateway/pairing.py`가 상위 집합 |
| `src/adapters/security.ts` | Hermes `allowed_users_env` + `unauthorized_dm_behavior` |
| `src/adapters/outbound.ts` | 원본에서도 `{success:true}` 반환하는 스텁이었음 |
| `src/relay/session-store.ts` | `mutateConfigFile`로 `openclaw.json`을 쓰던 호스트 결합 코드 |
| `openclaw.plugin.json` | `plugin.yaml`로 대체 |
| `package.json`의 `openclaw` 블록 | 〃 |

### 새로 만드는 것

| 파일 | 대응하는 OpenClaw 개념 |
|---|---|
| `plugin.yaml` | `openclaw.plugin.json` (단, 필드 체계가 완전히 다름) |
| `__init__.py` `register(ctx)` | `index.ts`의 `plugin.register(api)` |
| `registration.py` | `src/channel.ts`의 `kakaoPlugin` 기술자 |
| `adapter.py` | `src/adapters/gateway.ts` (997줄 → 3개 추상 메서드 중심으로 축소) |
| `commands.py` | `src/commands/card.ts` + gateway.ts의 명령 하이재킹 |

## 3. 개념 대응

| OpenClaw | Hermes |
|---|---|
| `plugin.register(api)` | `register(ctx)` |
| `api.registerChannel({plugin})` | `ctx.register_platform(name, label, adapter_factory, check_fn, ...)` |
| 채널 기술자 객체(`config`/`gateway`/`status`/… 어댑터 묶음) | `BasePlatformAdapter` 서브클래스 + `PlatformEntry` 콜백들 |
| `gateway.startAccount(ctx)` / `stopAccount()` | `connect(*, is_reconnect)` / `disconnect()` |
| `outbound.sendText` / `sendMedia` | `send(chat_id, content, reply_to, metadata)` |
| `runtime.logger.*` | 모듈 수준 `logging.getLogger(__name__)` |
| `runtime.config.mutateConfigFile()` | **대응물 없음** — env + `PlatformConfig`, 설정 파일 자가 수정 안 함 |
| `runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher` | `await self.handle_message(event)` (코어가 핸들러 소유) |
| 손으로 만든 inbound context 딕셔너리 | `MessageEvent` + `SessionSource` |
| `SessionKey: agent:main:kakao-talkchannel:dm:{u}` | `build_session_key()` → `agent:main:kakaotalk:dm:{u}` |
| `configSchema` (Zod → JSON Schema 이중 관리) | `plugin.yaml` env 선언 + `validate_config` 콜백 |
| `capabilities: {chatTypes, media, ...}` | `PlatformEntry` 필드 (`max_message_length`, `pii_safe`, …) |
| `status.probeAccount` / `buildAccountSnapshot` | `is_connected` / `_mark_connected` / `_set_fatal_error` |
| `setup.*` (`resolveTalkChannelId` 등) | `setup_fn` (대화형 설치) |
| `accounts.<id>` 다중 계정 | **없음** — 프로필 분리로 대체 |
| `dmPolicy: pairing\|allowlist\|open\|disabled` | `unauthorized_dm_behavior: "pair"\|"ignore"` + `allowed_users_env` |

## 4. 원본에서 고쳐서 가져갈 것

이식은 알려진 결함을 정리할 기회입니다.

1. **스키마 이중 관리** — 원본은 `openclaw.plugin.json`의 JSON Schema와
   `src/config/schema.ts`의 Zod가 손으로 동기화되며 **이미 어긋나 있었습니다**
   (`reconnectDelayMs`, `maxReconnectDelayMs`, `textChunkLimit`, `chunkMode`가
   매니페스트에 없음). Python 판은 `config.py`를 단일 출처로 두고 `plugin.yaml`은
   env 선언만 갖게 합니다.
2. **`gateway.ts` 997줄** — 호스트 디스패치 + 세션 토큰 수명주기 + LRU 활동
   추적 + `/compact` 넛지 휴리스틱 + 카드 스니핑 + 한국어 UI 카루셀이 한 파일에
   섞여 있었습니다. `adapter.py` / `commands.py` / `transport/` 로 분리합니다.
3. **슬래시 URL 처리 불일치** — `client.ts`·`status.ts`는 `${relayUrl}/health`,
   gateway는 `${relayUrl}health`를 씁니다. `config.py`에서 릴레이 URL을
   한 번 정규화합니다.
4. **`tests/setup.ts`가 실제로 로드되지 않음** — `vitest.config.ts`에
   `setupFiles`가 설정되어 있지 않아 전역 `beforeEach(vi.clearAllMocks)`가
   등록된 적이 없습니다. pytest `conftest.py`는 자동 로드되므로 이 문제는 사라집니다.
5. **테스트가 타입체크에서 제외됨** — `tsconfig.json`이 `tests`를 excludes.
   Python 판은 `mypy`/`pyright` 대상에 테스트를 포함시킵니다.
6. **릴레이 와이어 스펙 문서 부재** — `src/types.ts:7`, `kakao/payload.ts:5`,
   `kakao/callback.ts:7`이 참조하는 `docs/relay-server-api-spec.md`와
   `docs/implementation-plan.md`가 원본 저장소에 **존재하지 않습니다.**
   A안을 택한다면 이 스펙을 코드에서 역으로 문서화하는 것이 선행 작업입니다.

## 5. 이식 대상 릴레이 와이어 프로토콜 (코드에서 추출)

| 목적 | 엔드포인트 |
|---|---|
| 세션 생성 (비인증) → `{sessionToken, pairingCode, expiresIn, status}` | `POST {relay}v1/sessions/create` |
| 세션 상태 | `GET {relay}v1/sessions/{token}/status` |
| 인바운드 스트림 | `GET {relay}v1/events` (Bearer, `text/event-stream`, `Last-Event-ID` 재개) |
| 응답 전송 | `POST {relay}openclaw/reply` — body `{messageId, response}` |
| 헬스체크 | `GET {relay}/health` |

SSE 이벤트: `message | ping | error | pairing_complete | pairing_expired`.
`InboundMessage = {id, conversationKey, kakaoPayload?, normalized:{userId,text,channelId}, createdAt}`.

토큰 해결 순서: config `sessionToken` → config `relayToken` → env → `createSession()`.
401/410 → 토큰 폐기 후 재발급. `pairing_complete` 수신 시 의도적 스트림 재접속.

> `POST {relay}openclaw/reply`의 경로에 `openclaw`가 박혀 있습니다. 릴레이를
> 그대로 쓴다면 호스트 중립 경로 추가를 릴레이 쪽에 요청하거나, 이 경로를
> 그대로 호출하되 이름이 오해를 부른다는 점을 문서화해야 합니다.
