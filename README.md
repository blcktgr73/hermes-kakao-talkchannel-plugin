# hermes-kakao-talkchannel-plugin

[Nous Research Hermes Agent](https://github.com/NousResearch/hermes-agent)용
카카오톡 채널(KakaoTalk Channel) 플랫폼 어댑터 플러그인.

[`openclaw-kakao-talkchannel-plugin`](https://github.com/blcktgr73/openclaw-kakao-talkchannel-plugin)
(TypeScript / OpenClaw)을 Python / asyncio로 이식했습니다.

> **상태: 초기 개발 단계 (v0.1.0).**
> 순수 도메인 계층, 릴레이 트랜스포트, 페어링 CLI까지 구현·테스트 완료(274개 통과).
> 어댑터가 실제 Hermes 게이트웨이에 붙는 것은 **아직 검증되지 않았습니다** —
> 아래 "검증되지 않은 것" 참고.

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

## 검증되지 않은 것

정직하게 적어둡니다. 아래는 **실제 Hermes 설치본으로 확인되지 않았습니다.**

1. **`BasePlatformAdapter`의 import 경로.** `hermes_compat.py`가 세 후보
   경로를 시도하고 실패하면 스텁으로 떨어집니다. 실제 pip 설치본에서
   어느 경로인지 확인 필요.
2. **`setup_fn`의 시그니처.** `interactive_setup()`은 대화형 마법사인 척하지
   않고 필요한 환경변수를 안내하는 자리표시자입니다.
3. **엔드투엔드 왕복.** 카카오톡 → 릴레이 → 에이전트 → 응답 경로를 실제로 태워본
   적이 없습니다.
4. **카카오의 선제 발송(push) 가능 여부.** 에이전트 세션은 3~30분, 카카오 콜백
   창은 ~5초라 ack-then-push가 필수인데, 릴레이가 이를 어떻게 처리하는지
   확인되지 않았습니다. 설계 전체의 전제입니다.

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
