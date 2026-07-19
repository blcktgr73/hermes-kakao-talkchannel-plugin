"""Plugin configuration.

Single source of truth for config shape — unlike the OpenClaw plugin, which kept
a Zod schema and a hand-written JSON Schema in the manifest and let them drift
(docs/02-openclaw-port-map.md §4). ``plugin.yaml`` here declares env vars only.

Precedence follows Hermes convention: environment variables override
``config.yaml``'s ``gateway.platforms.kakaotalk.extra``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from .kakao.chunking import ChunkMode
from .transport.session import DEFAULT_RELAY_URL

PLATFORM_NAME = "kakaotalk"
PLATFORM_LABEL = "KakaoTalk"

_VALID_CHUNK_MODES: tuple[ChunkMode, ...] = ("sentence", "newline", "length")

_TEXT_CHUNK_LIMIT_MIN = 100
_TEXT_CHUNK_LIMIT_MAX = 1000
_RECONNECT_DELAY_MIN = 500
_RECONNECT_DELAY_MAX = 10000
_MAX_RECONNECT_DELAY_MIN = 5000
_MAX_RECONNECT_DELAY_MAX = 60000


@dataclass
class KakaoConfig:
    """Resolved KakaoTalk channel configuration."""

    enabled: bool = True
    channel_id: str | None = None
    relay_url: str = DEFAULT_RELAY_URL
    relay_token: str | None = None
    session_token: str | None = None
    response_prefix: str = ""
    allow_from: list[str] = field(default_factory=list)
    allow_all_users: bool = False
    home_channel: str | None = None
    text_chunk_limit: int = 400
    chunk_mode: ChunkMode = "sentence"
    reconnect_delay_ms: int = 1000
    max_reconnect_delay_ms: int = 30000

    def is_configured(self) -> bool:
        """A relay URL is always present, so the plugin can always attempt pairing."""
        return bool(self.relay_url)


@dataclass(frozen=True)
class ConfigValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _env_str(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _env_int(name: str) -> int | None:
    value = os.environ.get(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_config(extra: dict[str, Any] | None = None) -> KakaoConfig:
    """Build a config from ``config.yaml`` extras overlaid with environment variables."""
    extra = extra or {}
    config = KakaoConfig()

    # Layer 1: config.yaml -> gateway.platforms.kakaotalk.extra
    config.enabled = bool(extra.get("enabled", True))
    config.channel_id = extra.get("channel_id") or extra.get("channelId")
    config.relay_url = extra.get("relay_url") or extra.get("relayUrl") or DEFAULT_RELAY_URL
    config.relay_token = extra.get("relay_token") or extra.get("relayToken")
    config.session_token = extra.get("session_token") or extra.get("sessionToken")
    config.response_prefix = extra.get("response_prefix") or extra.get("responsePrefix") or ""
    config.home_channel = extra.get("home_channel") or extra.get("homeChannel")

    allow_from = extra.get("allow_from") or extra.get("allowFrom") or []
    config.allow_from = list(allow_from) if isinstance(allow_from, list) else _split_csv(allow_from)

    config.text_chunk_limit = int(
        extra.get("text_chunk_limit") or extra.get("textChunkLimit") or 400
    )
    config.chunk_mode = extra.get("chunk_mode") or extra.get("chunkMode") or "sentence"
    config.reconnect_delay_ms = int(
        extra.get("reconnect_delay_ms") or extra.get("reconnectDelayMs") or 1000
    )
    config.max_reconnect_delay_ms = int(
        extra.get("max_reconnect_delay_ms") or extra.get("maxReconnectDelayMs") or 30000
    )

    # Layer 2: environment overrides
    config.relay_url = _env_str("KAKAO_RELAY_URL") or config.relay_url
    config.relay_token = _env_str("KAKAO_RELAY_TOKEN") or config.relay_token
    config.session_token = _env_str("KAKAO_SESSION_TOKEN") or config.session_token
    config.home_channel = _env_str("KAKAO_HOME_CHANNEL") or config.home_channel
    config.response_prefix = _env_str("KAKAO_RESPONSE_PREFIX") or config.response_prefix
    config.channel_id = _env_str("KAKAO_CHANNEL_ID") or config.channel_id

    env_allow = _split_csv(_env_str("KAKAO_ALLOWED_USERS"))
    if env_allow:
        config.allow_from = env_allow
    config.allow_all_users = _env_bool("KAKAO_ALLOW_ALL_USERS") or config.allow_all_users

    env_chunk_limit = _env_int("KAKAO_TEXT_CHUNK_LIMIT")
    if env_chunk_limit is not None:
        config.text_chunk_limit = env_chunk_limit

    env_chunk_mode = _env_str("KAKAO_CHUNK_MODE")
    if env_chunk_mode in _VALID_CHUNK_MODES:
        config.chunk_mode = env_chunk_mode  # type: ignore[assignment]

    return config


def validate_config(config: KakaoConfig) -> ConfigValidation:
    """Check ranges that the original enforced through Zod."""
    errors: list[str] = []

    if not config.relay_url:
        errors.append("relay_url is required")

    if not (_TEXT_CHUNK_LIMIT_MIN <= config.text_chunk_limit <= _TEXT_CHUNK_LIMIT_MAX):
        errors.append(
            f"text_chunk_limit must be between {_TEXT_CHUNK_LIMIT_MIN} "
            f"and {_TEXT_CHUNK_LIMIT_MAX} (got {config.text_chunk_limit})"
        )

    if config.chunk_mode not in _VALID_CHUNK_MODES:
        errors.append(
            f"chunk_mode must be one of {', '.join(_VALID_CHUNK_MODES)} (got {config.chunk_mode})"
        )

    if not (_RECONNECT_DELAY_MIN <= config.reconnect_delay_ms <= _RECONNECT_DELAY_MAX):
        errors.append(
            f"reconnect_delay_ms must be between {_RECONNECT_DELAY_MIN} "
            f"and {_RECONNECT_DELAY_MAX} (got {config.reconnect_delay_ms})"
        )

    if not (
        _MAX_RECONNECT_DELAY_MIN <= config.max_reconnect_delay_ms <= _MAX_RECONNECT_DELAY_MAX
    ):
        errors.append(
            f"max_reconnect_delay_ms must be between {_MAX_RECONNECT_DELAY_MIN} "
            f"and {_MAX_RECONNECT_DELAY_MAX} (got {config.max_reconnect_delay_ms})"
        )

    return ConfigValidation(ok=not errors, errors=errors)
