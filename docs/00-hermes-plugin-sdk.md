# Hermes Agent 플러그인 SDK 조사 결과

조사 대상: `github.com/NousResearch/hermes-agent` @ `main` (MIT, `version = 0.18.2`).
아래 인용은 모두 `raw.githubusercontent.com` 및 GitHub trees API로 직접 확인한
소스 기준입니다. 확인하지 못한 항목은 §9에 따로 적었습니다.

## 1. 결론: 플랫폼 어댑터는 1급 확장점이다

Hermes 플러그인은 4종류(general / memory provider / context engine / model provider)로
문서화되어 있지만, 실제로는 `kind: platform`이라는 별도 종류가 있고 이것이 게이트웨이
메시징 채널(Telegram, Discord, Slack, LINE, IRC …)을 추가하는 공식 경로입니다.
카카오톡 채널은 여기에 정확히 들어맞습니다.

핵심 파일:

| 파일 | 역할 |
|---|---|
| `gateway/platforms/base.py` | `BasePlatformAdapter` ABC, `MessageEvent`, `SendResult`, `SessionSource` |
| `gateway/platform_registry.py` | `PlatformEntry`, 지연 로딩 레지스트리 |
| `hermes_cli/plugins.py` | `PluginContext`, 매니페스트 파싱, 4종 디스커버리 |
| `gateway/session.py` | `build_session_key()` — 대화 정체성의 SSOT |
| `gateway/config.py` | `PlatformConfig`, YAML/env 병합 |
| `gateway/pairing.py` | DM 페어링 코드 기반 접근 제어 |
| **`plugins/platforms/line/adapter.py`** | **카카오톡에 가장 가까운 참조 구현** |

## 2. 매니페스트 — `plugin.yaml`

`plugins/platforms/line/plugin.yaml` (발췌, 원문):

```yaml
name: line-platform
label: LINE
kind: platform
version: 1.0.0
description: >
  LINE Messaging API gateway adapter for Hermes Agent.
author: Hermes Agent contributors
requires_env:
  - name: LINE_CHANNEL_ACCESS_TOKEN
    description: "LINE channel long-lived access token (...)"
    prompt: "LINE channel access token"
    url: "https://developers.line.biz/console/"
    password: true
optional_env:
  - name: LINE_ALLOWED_USERS
    description: "Comma-separated LINE user IDs allowed to DM the bot (U-prefixed)"
    prompt: "Allowed user IDs (comma-separated)"
    password: false
```

주의할 함정 두 가지 (소스에서 확인):

- 매니페스트를 **서로 다른 두 소비자**가 각각 다른 필드 집합으로 읽습니다.
  `PluginManager._parse_manifest`가 만드는 `PluginManifest`에는 `label`과
  `optional_env` 필드가 **없습니다**. 이 둘은 `hermes_cli/config.py`가 import 시점에
  `plugins/platforms/*/plugin.yaml`을 스캔해 `OPTIONAL_ENV_VARS`를 채우는 경로로
  따로 소비됩니다. 두 블록 모두 유효하지만 경로가 다릅니다.
- `kind: platform`은 `_VALID_PLUGIN_KINDS`로 검증되며, **오타가 나면 조용히
  `standalone`으로 격하되어 어댑터가 아예 등록되지 않습니다.**

`requires_env` 항목 키: `name`(필수), `description`, `prompt`, `url`,
`password`(생략 시 `*_TOKEN`/`*_SECRET`/`*_KEY`/`*_PASSWORD`/`*_JSON`에서 자동 추론),
`category`(기본 `"messaging"`). 문자열 하나만 써도 됩니다.

번들 플랫폼은 자동 로드되지만, 사용자 설치 플러그인(`~/.hermes/plugins/`)은
`plugins.enabled` 게이트를 통과해야 합니다 — 신뢰되지 않은 코드로 취급됩니다.

## 3. 진입점 — `register(ctx)`

```python
def register(ctx) -> None:
```

`ctx`는 `hermes_cli.plugins.PluginContext`. 등록 가능한 표면:
`register_tool`, `register_cli_command`, `register_command`, `register_hook`,
`register_middleware`, `register_skill`, **`register_platform`**,
`register_slack_action_handler`, `register_auxiliary_task`, `register_context_engine`,
`register_secret_source`, 그리고 각종 provider 등록자. 추가로 `dispatch_tool`,
`inject_message`, 속성 `ctx.llm`, `ctx.profile_name`.

> **`ctx.config`와 `ctx.logger`는 존재하지 않습니다** (소스에서 부재 확인).
> 설정은 `os.getenv()` + 팩토리에 주입되는 `PlatformConfig`로 읽고, 로깅은
> 모듈 수준 `logger = logging.getLogger(__name__)`을 씁니다. OpenClaw의
> `runtime.logger` / `runtime.config`에 대응하는 것이 없다는 뜻입니다.

## 4. `ctx.register_platform()`

```python
def register_platform(
    self,
    name: str,
    label: str,
    adapter_factory: Callable,
    check_fn: Callable,
    validate_config: Callable | None = None,
    required_env: list | None = None,
    install_hint: str = "",
    **entry_kwargs: Any,
) -> None:
```

문서 주석 원문:

> The adapter_factory receives a ``PlatformConfig`` and returns a
> `BasePlatformAdapter` subclass instance. The gateway calls ``check_fn()``
> before instantiation to verify dependencies.
> Extra keyword arguments are forwarded to ``PlatformEntry`` ...
> **Unknown keys raise TypeError from the dataclass constructor.**

`**entry_kwargs`로 넘길 수 있는 `PlatformEntry` 필드 전체:
`is_connected`, `setup_fn`, `plugin_name`, `allowed_users_env`, `allow_all_env`,
`max_message_length`(0 = 무제한), `pii_safe`, `emoji`(기본 `"🔌"`),
`allow_update_command`(기본 True), `platform_hint`, `env_enablement_fn`,
`apply_yaml_config_fn`, `cron_deliver_env_var`, `standalone_sender_fn`.

LINE의 실제 호출 (원문):

```python
def register(ctx) -> None:
    """Plugin entry point — called by the Hermes plugin system at startup."""
    ctx.register_platform(
        name="line",
        label="LINE",
        adapter_factory=lambda cfg: LineAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=["LINE_CHANNEL_ACCESS_TOKEN", "LINE_CHANNEL_SECRET"],
        install_hint="pip install aiohttp",
        setup_fn=interactive_setup,
        env_enablement_fn=_env_enablement,
        cron_deliver_env_var="LINE_HOME_CHANNEL",
        standalone_sender_fn=_standalone_send,
        allowed_users_env="LINE_ALLOWED_USERS",
        allow_all_env="LINE_ALLOW_ALL_USERS",
        max_message_length=LINE_SAFE_BUBBLE_CHARS,
        emoji="💚",
        pii_safe=False,
        allow_update_command=True,
        platform_hint=(...),
    )
```

**지연 로딩**: 레지스트리는 인자 없는 로더만 등록하고 실제 조회 시점에 모듈을
import합니다. 이유는 소스 주석에 명시 — 어댑터가 모듈 최상단에서 무거운 플랫폼 SDK를
import하면 *모든* `hermes` 호출에 수 초가 붙기 때문. **카카오/HTTP SDK import는
지연시키거나 `check_fn` 내부에 둘 것.**

## 5. `BasePlatformAdapter` — 반드시 구현할 것

추상 메서드는 **3개뿐**입니다.

```python
@abstractmethod
async def connect(self, *, is_reconnect: bool = False) -> bool:

@abstractmethod
async def disconnect(self) -> None:

@abstractmethod
async def send(
    self,
    chat_id: str,
    content: str,
    reply_to: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> SendResult:
```

`connect`의 `is_reconnect` 주석 원문:

> `is_reconnect`: False on a cold first boot ...; True when the reconnect watcher
> is re-establishing a platform that was previously running and dropped after an
> outage. Adapters that buffer a server-side update queue ... should preserve that
> queue when ``is_reconnect`` is True so messages sent during the outage are
> delivered rather than silently discarded.

생성자: `def __init__(self, config: PlatformConfig, platform: Platform)`.
`Platform`은 enum이지만 `Platform._missing_()`이 임의 이름을 허용하므로
**`Platform("kakaotalk")`은 코어 수정 없이 동작합니다.**

선택 오버라이드 (관련 있는 것만): `send_typing`, `stop_typing`, `_keep_typing`,
`edit_message`, `delete_message`, `send_image`, `send_document`, `send_draft`,
`render_message_event`, `format_tool_event`. 라이프사이클 헬퍼:
`_mark_connected()`, `_mark_disconnected()`,
`_set_fatal_error(code, message, *, retryable)`,
`_acquire_platform_lock(scope, identity, resource_desc)` / `_release_platform_lock()`.

스트리밍/청킹 훅: `supports_draft_streaming()`, `prefers_fresh_final_streaming()`,
`streaming_overflow_limit()`, `message_len_fn`(UTF-16 계수용 `utf16_len` 제공),
`REQUIRES_EDIT_FINALIZE: bool = False`.
**청킹 자체는 레지스트리의 `max_message_length`가 중앙에서 구동합니다** —
어댑터가 직접 자르지 않습니다.

## 6. 인바운드 정규화와 코어로의 디스패치

어댑터는 `self.build_source(...)`로 `SessionSource`를 만들고 `MessageEvent`로 감싼 뒤
`await self.handle_message(event)`를 호출합니다. LINE 원문:

```python
source_obj = self.build_source(
    chat_id=chat_id, chat_type=chat_type,
    user_id=user_id, user_name=user_id, chat_name=chat_id,
)
event_obj = MessageEvent(
    text=text,
    message_type=_LINE_MESSAGE_TYPES.get(msg_type, MessageType.TEXT),
    source=source_obj, raw_message=event, message_id=message_id,
    media_urls=media_urls, media_types=media_types,
)
await self.handle_message(event_obj)
```

`MessageEvent` 필드 ("Normalized representation that all adapters produce"):
`text`, `message_type`, `source`, `raw_message`, `message_id`, `platform_update_id`,
`media_urls`(**원격 URL이 아니라 로컬 파일 경로** — 비전 툴 접근용), `media_types`,
`reply_to_message_id`, `reply_to_text`, `reply_to_author_id`, `reply_to_author_name`,
`reply_to_is_own_message`, `auto_skill`, `channel_prompt`, `channel_context`,
`internal`, `metadata`, `timestamp`.

`MessageType` = `TEXT, LOCATION, PHOTO, VIDEO, AUDIO, VOICE, DOCUMENT, STICKER, COMMAND`.

`SendResult` = `success`, `message_id`, `error`, `raw_response`, `retryable`,
`retry_after`, `continuation_message_ids`, `error_kind`(`classify_send_error`로 설정).

에이전트 호출은 **직접 하지 않습니다**. 게이트웨이가 `set_message_handler`로 꽂아둔
`MessageHandler = Callable[[MessageEvent], Awaitable[Optional[Union[str, EphemeralReply]]]]`을
`handle_message`가 대신 호출합니다. 주석 원문:

> This method returns quickly by spawning background tasks. This allows new
> messages to be processed even while an agent is running, enabling interruption
> support.

**대화 정체성**은 `build_session_key(source, group_sessions_per_user=True,
thread_sessions_per_user=False, profile=None)`가 SSOT이고 형식은
`{ns}:{platform}:{chat_type}:{chat_id}[:{thread_id}]` — 예: `agent:main:line:dm:U123`.
DM 키는 `chat_id` 우선, 없으면 `user_id_alt or user_id`(사용자 간 히스토리 누출 방지),
그 다음 `thread_id`.

## 7. 설정과 시크릿

3계층, 모두 확인됨:

1. **`config.yaml`** — `gateway.platforms.<name>.enabled` + `.extra.*`가
   `PlatformConfig`(`enabled, token, api_key, home_channel, reply_to_mode,
   gateway_restart_notification, typing_indicator, typing_status_text,
   channel_overrides, extra`)로 역직렬화. 플랫폼 고유 키는
   `apply_yaml_config_fn(yaml_cfg, platform_cfg) -> Optional[dict]`가 담당.
2. **환경변수** (일반적 경로) — `env_enablement_fn() -> Optional[dict]`가 어댑터
   생성 **이전에** `PlatformConfig.extra`를 채워서, SDK를 인스턴스화하지 않고도
   `hermes status`가 동작하게 합니다.
3. **시크릿**은 `~/.hermes/.env`, 매니페스트에서 `password: true`. 별도
   `register_secret_source` 확장점도 있음.

우선순위는 관례상 env > YAML(`not os.getenv(...)` 가드).
`apply_yaml_config_fn`의 예외는 삼켜지고 debug 레벨로만 로깅됩니다 — 잘못 만든
플러그인이 게이트웨이 설정 로드를 중단시키지 못하게.

> **다중 계정: 네이티브 지원 없음.** `GatewayConfig.platforms`는
> `Dict[Platform, PlatformConfig]`라 플랫폼당 설정이 정확히 하나입니다.
> 우회책은 (a) Hermes **프로필**(별도 `HERMES_HOME`, `_acquire_platform_lock`이
> 두 프로필의 자격증명 공유를 차단, `gateway.profile_routes`로 라우팅) 또는
> (b) 서로 다른 플랫폼 이름을 여러 개 등록. OpenClaw의 `accounts.<id>` 구조와
> 가장 크게 갈리는 지점입니다.

## 8. 접근 제어 — 네이티브로 충분히 강함

- **허용목록**: 레지스트리 엔트리의 `allowed_users_env`(쉼표 구분 ID),
  `allow_all_env`(개발용 우회).
- **DM 페어링이 기본값**: `unauthorized_dm_behavior: str = "pair"`(`"pair"` | `"ignore"`).
  `gateway/pairing.py` 주석 원문: *"Instead of static allowlists with user IDs,
  unknown users receive a one-time pairing code that the bot owner approves via
  the CLI."* 32자 비혼동 알파벳(`0/O/1/I` 제외)에서 8자, `secrets.choice()`,
  TTL 1시간, 플랫폼당 대기 최대 3개, 사용자당 10분에 1회, 5회 실패 시 잠금,
  `chmod 0600`, 코드는 절대 로깅 안 함. 승인 시 허용목록 env에도 기록.
- 어댑터측 훅: `set_authorization_check(...)`, `_is_sender_authorized(...)`,
  그리고 상류에서 인증하는 플랫폼용 opt-out 속성 `enforces_own_access_policy` /
  `authorization_is_upstream`.

**결과: OpenClaw 플러그인의 `dmPolicy` / 페어링 코드 로직은 이식하지 않고 버립니다.
Hermes가 더 나은 것을 이미 갖고 있습니다.**

## 9. 확인하지 못한 것 / 문서화되지 않은 것

- `ctx.config`, `ctx.logger`: **부재를 확인**했습니다(추측 아님).
- `get_chat_info()`: 문서와 예제에 나오지만 `base.py` 개요에서 추상/정의 메서드로
  찾지 못했습니다. 강제 계약이 아니라 선택적 관례로 취급하십시오.
- 플러그인별 의존성 선언: 공식 메커니즘 없음. `check_fn`이 False를 반환하고
  `install_hint="pip install ..."`를 주는 것이 관례.
- `apps/desktop/src/plugins/README.md`는 미검토 — 데스크톱 표면이 필요하면 추가 조사 필요.

## 10. 카카오톡 설계에 직접 영향을 주는 두 가지 (검증됨)

1. **웹훅 ACK 데드라인.** 문서 원문: *"For platforms with tight response deadlines
   (e.g., WeCom's 5-second limit), always acknowledge immediately and deliver the
   agent's reply proactively via API later. Agent sessions run 3–30 minutes —
   inline replies within a callback response window are not feasible."*
   카카오 스킬 서버 콜백 창도 ~5초이므로 **ack-then-push**가 강제됩니다.
2. **무료 응답 vs 과금 발송.** LINE 어댑터는 reply token 만료 때문에
   `RequestCache` 상태 기계(`PENDING → READY → DELIVERED`/`ERROR`)와
   45초 시점 postback 버튼을 쏘는 `_keep_typing` 오버라이드를 갖고 있습니다.
   **카카오의 콜백 vs 푸시 경제학이 정확히 같은 모양이므로, 설계 전에
   `plugins/platforms/line/adapter.py`를 통독할 것.**

또한 `_SYSTEM_BYPASS_PREFIXES`(`⚡ Interrupting`, `⏳ Queued`, `⏩ Steered`, `💾`)는
어떤 캐싱을 얹더라도 항상 그대로 렌더링되어야 합니다.

## 참고 링크

- [NousResearch/hermes-agent (GitHub)](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent Docs](https://hermes-agent.nousresearch.com/docs/)
- [Plugins (user guide)](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
- [Build a Hermes Plugin](https://hermes-agent.nousresearch.com/docs/guides/build-a-hermes-plugin)
- [awesome-hermes-agent](https://github.com/0xNyk/awesome-hermes-agent)
