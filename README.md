# hermes-kakao-talkchannel-plugin

[Nous Research Hermes Agent](https://github.com/NousResearch/hermes-agent)용
카카오톡 채널(KakaoTalk Channel) 플랫폼 어댑터 플러그인.

[`openclaw-kakao-talkchannel-plugin`](https://github.com/blcktgr73/openclaw-kakao-talkchannel-plugin)
(TypeScript / OpenClaw)을 Python / asyncio로 이식했습니다.

> **상태: 실기 검증 완료 (v0.1.0).**
> 2026-07-20에 실제 Hermes 게이트웨이(0.18.2)에서 검증했습니다 — 플러그인 로드,
> 플랫폼 등록, 릴레이 페어링, 카카오톡 대화 왕복, `hermes kakao pairing status`
> 전부 동작합니다. 310개 테스트 통과.

## 운영자용 페어링 CLI

```bash
hermes kakao pairing status   # 현재 코드 조회 (몇 번이든 가능)
hermes kakao pairing new      # 재시작 없이 세션 폐기 후 새 코드 발급
```

Hermes에는 실행 중인 게이트웨이로 들어가는 제어 채널이 없으므로, 게이트웨이가 상태를
파일로 발행하고 CLI가 그것을 읽습니다. 자세한 내용은
[docs/PAIRING_OPERATIONS.md](docs/PAIRING_OPERATIONS.md).

이 설계는 [OpenClaw 판](https://github.com/blcktgr73/openclaw-kakao-talkchannel-plugin)에서
실기 검증을 마친 뒤 이식했습니다.

## 동작 방식

```
카카오톡 사용자
   │ 오픈빌더 스킬 콜백 (~5초 데드라인)
   ▼
릴레이 서버 ──── SSE ────▶ KakaoAdapter ──▶ Hermes 코어
   ▲                                            │
   └──────── POST reply ────────────────────────┘
```

카카오는 공개 HTTPS 엔드포인트를 요구하지만 Hermes 게이트웨이는 보통 개인
머신에서 돕니다. 릴레이가 그 간극을 메웁니다.

> ⚠️ **기본 릴레이는 제3자가 운영하며 대화 평문을 볼 수 있습니다.**
> 민감한 용도라면 반드시 [docs/relay-trust-boundary.md](docs/relay-trust-boundary.md)를
> 먼저 읽고 자체 릴레이를 쓰십시오.

## 설치

### pip

```bash
pip install hermes-kakao-talkchannel
```

`hermes_agent.plugins` 엔트리포인트로 자동 등록됩니다.

### 드롭인 디렉터리

```bash
git clone https://github.com/blcktgr73/hermes-kakao-talkchannel-plugin \
  ~/.hermes/plugins/kakao-talkchannel
pip install aiohttp PyYAML
```

### 활성화

사용자 설치 플러그인은 기본 비활성입니다.

```bash
hermes plugins enable kakao-talkchannel
hermes status
```

## 설정

전부 선택 사항입니다 — 아무것도 설정하지 않으면 기본 릴레이로 페어링을 시작합니다.

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `KAKAO_RELAY_URL` | `https://k.tess.dev/` | 릴레이 베이스 URL |
| `KAKAO_RELAY_TOKEN` | — | 장기 릴레이 토큰. 없으면 대화형 페어링 |
| `KAKAO_SESSION_TOKEN` | — | 세션 토큰 (보통 페어링 후 자동 저장) |
| `KAKAO_ALLOWED_USERS` | — | 쉼표 구분 `botUserKey` 허용목록 |
| `KAKAO_ALLOW_ALL_USERS` | `false` | 허용목록 우회 (개발용) |
| `KAKAO_HOME_CHANNEL` | — | cron/선제 발송 기본 대상 |
| `KAKAO_RESPONSE_PREFIX` | — | 모든 응답 앞에 붙일 문자열 |
| `KAKAO_TEXT_CHUNK_LIMIT` | `400` | 청크당 문자 수 (100–1000) |
| `KAKAO_CHUNK_MODE` | `sentence` | `sentence` \| `newline` \| `length` |

`~/.hermes/config.yaml`로도 설정할 수 있습니다 (환경변수가 우선):

```yaml
gateway:
  platforms:
    kakaotalk:
      enabled: true
      extra:
        relay_url: https://my-relay.example/
        response_prefix: "[봇] "
```

## 페어링

토큰 없이 게이트웨이를 시작하면 로그에 페어링 코드가 출력됩니다.

```
[kakao] Pairing required. Send this code to your KakaoTalk channel
within 60 minute(s): ABCD1234
```

카카오톡 채널에 그 코드를 보내면 페어링이 완료되고, 토큰이
`~/.hermes/kakao-talkchannel/session.json`에 저장되어 재시작 후에도 유지됩니다.

접근 제어는 Hermes의 기본 DM 페어링/허용목록을 그대로 씁니다 — 이 플러그인은
자체 DM 정책을 구현하지 않습니다.

## 개발

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"

.venv/bin/python -m pytest -q      # 193 passed
.venv/bin/python -m ruff check .
```

Hermes가 설치되어 있지 않아도 테스트는 돕니다 — `hermes_compat.py`가 최소
스텁으로 대체합니다. 다만 스텁 상태에서는 `check_requirements()`가 False를
반환해 실제 게이트웨이 기동을 막습니다.

## 구조

```
hermes_kakao_talkchannel/
  __init__.py        register(ctx) 진입점
  registration.py    ctx.register_platform 콜백 모음
  adapter.py         KakaoAdapter — connect / disconnect / send + 재발급 감시 루프
  config.py          설정 SSOT (env > YAML)
  hermes_compat.py   호스트 import + 테스트용 스텁
  kakao/             순수 도메인 (Hermes import 금지, AST 테스트로 강제)
  transport/         릴레이 SSE + HTTP 클라이언트
  pairing/           페어링 레지스트리 · 상태 파일 · 발행자 · CLI
```

## 실기에서 드러난 것 (2026-07-20)

소스만 읽고 쓴 호스트 계약이 **네 번 틀렸고**, 전부 실제 게이트웨이에서만 드러났습니다.

| 계약 | 잘못 안 것 | 실제 |
|---|---|---|
| `BasePlatformAdapter` 경로 | `hermes_agent.*` 하위로 추정 | 최상위 `gateway.platforms.base` |
| `get_chat_info` | "선택적 관례" | **추상 메서드** — 미구현 시 어댑터 생성 불가 |
| `is_connected` | 어댑터를 받는다 | **config**를 받고 자동 활성화를 결정 |
| `validate_config` | 에러 리스트 반환 | **bool** 반환. 빈 리스트가 falsy라 유효할 때 실패했다 |

배달 쪽에서는 더 근본적인 것이 나왔습니다. **인바운드 1건이 94번 재전송되어 94개
턴이 시작**된 적이 있습니다 — SSE 정상 종료 후 백오프 없는 재연결(제 결함)과 릴레이의
재flush(#90)가 곱해진 결과입니다. 오늘 관측된 거의 모든 이상 증상이 여기서 나왔습니다.

교훈 하나: 로컬 스텁 베이스가 실물보다 **느슨하면** 대역 노릇을 못 합니다. 평범한
클래스였던 스텁 때문에 추상 메서드 누락이 전 테스트를 통과했습니다. 지금은 같은 추상
집합을 선언하는 ABC입니다.

## 아직 확인되지 않은 것

1. **`setup_fn`의 시그니처.** `interactive_setup()`은 대화형 마법사인 척하지 않고
   필요한 환경변수를 안내하는 자리표시자입니다.
2. **프로파일 디렉터리.** 상태 파일이 `HERMES_HOME` 기준이라 Hermes 프로파일을
   타지 않습니다. VM당 에이전트 하나면 문제없지만 다중 프로파일에서는 고쳐야 합니다.
3. **긴 대화에서의 콜백 만료.** 응답이 콜백 TTL(약 55초)을 넘기면 유실됩니다.
   릴레이에 푸시 경로가 없다는 것이 관측으로 확인됐습니다.

또한 릴레이 클라이언트는 **알려진 결함을 의도적으로 그대로 이식**했습니다 —
[docs/known-relay-defects.md](docs/known-relay-defects.md) 참고.

## 문서

| 문서 | 내용 |
|---|---|
| [docs/README.md](docs/README.md) | 설계 문서 색인 |
| [docs/00-hermes-plugin-sdk.md](docs/00-hermes-plugin-sdk.md) | Hermes 플러그인 SDK 계약 |
| [docs/01-architecture.md](docs/01-architecture.md) | 아키텍처와 핵심 결정 |
| [docs/02-openclaw-port-map.md](docs/02-openclaw-port-map.md) | OpenClaw → Hermes 대응표 |
| [docs/03-implementation-plan.md](docs/03-implementation-plan.md) | 구현 계획과 열린 질문 |
| [docs/relay-wire-protocol.md](docs/relay-wire-protocol.md) | 릴레이 와이어 프로토콜 |
| [docs/relay-trust-boundary.md](docs/relay-trust-boundary.md) | 릴레이 신뢰 경계 ⚠️ |
| [docs/known-relay-defects.md](docs/known-relay-defects.md) | as-is 이식된 알려진 결함 |

## 라이선스

MIT
