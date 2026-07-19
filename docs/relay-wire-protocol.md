# 릴레이 와이어 프로토콜

> **출처 주의.** 이 문서는 `openclaw-kakao-talkchannel-plugin`의 **클라이언트
> 코드에서 역으로 추출**한 것입니다. 릴레이 서버측 권威 스펙이 아닙니다. OpenClaw
> 저장소의 `src/types.ts`, `src/kakao/payload.ts`, `src/kakao/callback.ts`가
> `docs/relay-server-api-spec.md`를 참조하지만 **그 파일은 존재하지 않습니다.**
>
> 실제 릴레이 동작과 어긋나는 부분이 발견되면 이 문서를 고치십시오.

베이스 URL 기본값: `https://k.tess.dev/` (트레일링 슬래시 포함)

## 엔드포인트 요약

| 목적 | 메서드 | 경로 | 인증 | 슬래시 정규화 | 타임아웃 |
|---|---|---|---|---|---|
| 세션 생성 | POST | `{base}v1/sessions/create` | 없음 | 함 | 없음 (D6) |
| 세션 상태 | GET | `{base}v1/sessions/{token}/status` | 경로 내 토큰 | 함 | 없음 (D6) |
| 인바운드 스트림 | GET | `{base}v1/events` | `Bearer` | 함 | 300s/시도 (D2) |
| 응답 전송 | POST | `{base}openclaw/reply` | `Bearer` | 함 | 10s |
| 헬스체크 | GET | `{relay_url}/health` | `Bearer` | **안 함 (D1)** | 10s |

`D<n>`은 [known-relay-defects.md](known-relay-defects.md) 참조.

## 1. 세션 생성

```http
POST {base}v1/sessions/create
Content-Type: application/json

{}
```

응답:

```json
{
  "sessionToken": "…",
  "pairingCode": "ABCD1234",
  "expiresIn": 3600,
  "status": "pending_pairing"
}
```

`status`: `pending_pairing | paired | expired | disconnected`

사용자는 `pairingCode`를 카카오톡 채널에 보내 페어링을 완료합니다. 클라이언트는
페어링이 **완료된 뒤에만** 토큰을 영속화해야 합니다 — 페어링 코드가 만료되면
릴레이가 세션을 삭제하므로, 미페어링 토큰을 저장하면 다음 시작 시 401이 확정입니다.

## 2. 세션 상태 조회

```http
GET {base}v1/sessions/{sessionToken}/status
Accept: application/json
```

```json
{ "status": "paired", "pairedAt": "2026-07-19T09:00:00Z", "kakaoUserId": "…" }
```

토큰이 헤더가 아니라 **경로**에 들어가며 URL 인코딩되지 않습니다.

## 3. 인바운드 SSE 스트림

```http
GET {base}v1/events
Authorization: Bearer {sessionToken 또는 relayToken}
Accept: text/event-stream
Cache-Control: no-cache
Last-Event-ID: {마지막 이벤트 id}   ← 재개 시에만
```

상태 코드:

- `401`, `410` → 세션 무효. 재접속하지 않고 토큰을 폐기한 뒤 재페어링.
- 그 외 비-2xx → 일반 재시도 대상 (429/5xx 특별 처리 없음, `Retry-After` 미지원).

### 이벤트 타입

| `event:` | `data:` |
|---|---|
| `message` | `InboundMessage` (아래) |
| `ping` | `{}` — 킵얼라이브. **클라이언트가 무시함 (D4)** |
| `error` | `{ "code": "...", "message": "..." }` |
| `pairing_complete` | `{ "kakaoUserId": "...", "pairedAt": "..." }` |
| `pairing_expired` | `{ "reason": "..." }` |

`InboundMessage`:

```json
{
  "id": "msg-0001",
  "conversationKey": "conv-abc",
  "kakaoPayload": { "...": "원본 오픈빌더 SkillPayload (선택)" },
  "normalized": {
    "userId": "botuserkey-…",
    "text": "안녕하세요",
    "channelId": "@mychannel"
  },
  "createdAt": "2026-07-19T09:00:00.000Z"
}
```

`id`는 모든 이벤트 타입에서 재개 커서를 전진시킵니다(ping 포함).

`pairing_complete` 수신 시 클라이언트는 **의도적으로 스트림을 끊고 즉시 재접속**
합니다 — 새 스트림이 페어링된 계정 채널을 구독하도록. 이때 백오프도 재시도 카운트
증가도 없습니다.

## 4. 응답 전송

```http
POST {base}openclaw/reply
Authorization: Bearer {relayToken}
Content-Type: application/json

{
  "messageId": "msg-0001",
  "response": { "version": "2.0", "template": { "outputs": [...] } }
}
```

`response`는 카카오 오픈빌더 v2.0 스킬 응답 그대로입니다.

응답:

```json
{ "success": true, "deliveredAt": 1700000000 }
```

`success`가 boolean이 아니면 클라이언트가 거부합니다.

> 경로에 `openclaw`가 박혀 있습니다 (D7). 호스트 중립 별칭이 생기면 옮기는 것이
> 좋습니다.

## 5. 헬스체크

```http
GET {relay_url}/health
Authorization: Bearer {relayToken}
```

기본 URL이 슬래시로 끝나므로 실제 요청은 `https://k.tess.dev//health`가 됩니다 (D1).

## 토큰 해결 순서

1. 설정 `session_token`
2. 설정 `relay_token`
3. 환경변수 `KAKAO_RELAY_TOKEN`
4. 환경변수 `OPENCLAW_TALKCHANNEL_RELAY_TOKEN` (OpenClaw 설정 호환용, 이식본 추가)
5. `create_session()` → 페어링 코드 발급

빈 문자열은 falsy로 취급되어 다음 단계로 넘어갑니다.

## 재접속 백오프

```
delay = floor(min(base * 2^attempt, max) + min(base * 2^attempt, max) * 0.2 * random())
```

기본값 `base=1000ms`, `max=30000ms`. `attempt`는 이미 증가된 값이 넘어오므로 첫
재시도는 `attempt=1` → 2000~2399ms입니다. 지터가 상한 뒤에 더해져 최대 20%
초과합니다 (D3).

## 미확인 사항

- 릴레이가 멀티라인 `data:`를 보내는가? (D5의 영향 범위를 결정)
- ping 주기는? (D2/D4 수정 시 유휴 타임아웃 값 결정에 필요)
- 릴레이가 5초 카카오 콜백 데드라인을 어떻게 처리하는가 — 즉시 ACK 후 push인가,
  콜백 URL 보관인가? **설계 전체의 전제라 가장 중요합니다.**
- 세션 보존 기간, 로그 정책, 운영 주체.
