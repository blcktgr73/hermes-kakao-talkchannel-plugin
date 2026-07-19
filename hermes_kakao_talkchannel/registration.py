"""Registry callbacks handed to ``ctx.register_platform``.

Every keyword passed to ``register_platform`` must be a real ``PlatformEntry``
field — unknown keys raise ``TypeError`` from the dataclass constructor
(docs/00-hermes-plugin-sdk.md §4).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .config import KakaoConfig, load_config
from .config import validate_config as _validate_kakao_config
from .hermes_compat import HERMES_AVAILABLE
from .kakao.limits import KakaoLimits

logger = logging.getLogger(__name__)

INSTALL_HINT = "pip install aiohttp"


def check_requirements() -> bool:
    """Gate instantiation on importable dependencies.

    Called before the adapter is constructed, which is also why the aiohttp
    import lives in here rather than at module scope — the registry loads
    platform modules lazily to keep ``hermes`` CLI startup fast.
    """
    try:
        import aiohttp  # noqa: F401
    except ImportError:
        logger.warning("[kakao] aiohttp is not installed (%s)", INSTALL_HINT)
        return False

    if not HERMES_AVAILABLE:
        logger.error(
            "[kakao] Could not import the Hermes platform base class. "
            "The plugin is running against local test stubs and will not work."
        )
        return False

    return True


def validate_config(config: Any) -> Any:
    """Validate resolved config. Returns a list of error strings (empty = ok)."""
    extra = getattr(config, "extra", None) or {}
    result = _validate_kakao_config(load_config(extra))
    return result.errors


def is_connected(adapter: Any = None) -> bool:
    if adapter is None:
        return False
    return bool(getattr(adapter, "_connected", False))


def env_enablement() -> dict[str, Any] | None:
    """Seed ``PlatformConfig.extra`` from the environment before construction.

    Lets ``hermes status`` report the channel without importing aiohttp or
    touching the relay.
    """
    config: KakaoConfig = load_config({})

    extra: dict[str, Any] = {
        "relay_url": config.relay_url,
        "chunk_mode": config.chunk_mode,
        "text_chunk_limit": config.text_chunk_limit,
    }

    if config.relay_token:
        extra["relay_token"] = config.relay_token
    if config.session_token:
        extra["session_token"] = config.session_token
    if config.response_prefix:
        extra["response_prefix"] = config.response_prefix
    if config.channel_id:
        extra["channel_id"] = config.channel_id
    if config.home_channel:
        # The host turns `home_channel` into its HomeChannel dataclass.
        extra["home_channel"] = config.home_channel

    return extra


def apply_yaml_config(yaml_config: dict[str, Any], platform_config: Any) -> dict[str, Any] | None:
    """Merge ``gateway.platforms.kakaotalk.extra`` into the platform config.

    Exceptions raised here are swallowed and logged at debug level by the host,
    so failures are silent by design — keep this defensive.
    """
    extra = (yaml_config or {}).get("extra") or {}
    merged = dict(getattr(platform_config, "extra", None) or {})

    for key, value in extra.items():
        # Environment wins over YAML, matching Hermes convention.
        env_name = f"KAKAO_{key.upper()}"
        if os.environ.get(env_name):
            continue
        merged[key] = value

    return merged


async def interactive_setup(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Placeholder for ``hermes`` interactive setup.

    NOT IMPLEMENTED. The real signature of ``setup_fn`` was never verified
    against a Hermes install, so this returns the env vars a user must set
    instead of pretending to drive a wizard. See docs/03-implementation-plan.md Q8.
    """
    return {
        "status": "manual",
        "message": (
            "Set KAKAO_RELAY_URL (optional, defaults to https://k.tess.dev/) and start "
            "the gateway. A pairing code will be printed to the log — send it to your "
            "KakaoTalk channel to finish pairing."
        ),
    }


def register_platform(ctx: Any) -> None:
    """Register the KakaoTalk platform with the Hermes plugin context."""
    from .adapter import KakaoAdapter
    from .config import PLATFORM_LABEL, PLATFORM_NAME

    ctx.register_platform(
        name=PLATFORM_NAME,
        label=PLATFORM_LABEL,
        adapter_factory=lambda cfg: KakaoAdapter(cfg),
        check_fn=check_requirements,
        validate_config=validate_config,
        is_connected=is_connected,
        required_env=[],
        install_hint=INSTALL_HINT,
        setup_fn=interactive_setup,
        env_enablement_fn=env_enablement,
        apply_yaml_config_fn=apply_yaml_config,
        cron_deliver_env_var="KAKAO_HOME_CHANNEL",
        allowed_users_env="KAKAO_ALLOWED_USERS",
        allow_all_env="KAKAO_ALLOW_ALL_USERS",
        max_message_length=KakaoLimits.SIMPLE_TEXT_MAX,
        emoji="💛",
        pii_safe=False,
        allow_update_command=True,
        platform_hint=(
            "KakaoTalk Channel via relay. Replies are plain text — KakaoTalk renders "
            "no markdown, so avoid tables and code fences."
        ),
    )
