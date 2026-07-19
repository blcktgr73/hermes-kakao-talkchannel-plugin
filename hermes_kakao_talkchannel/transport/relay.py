"""Relay stream orchestration: token resolution, pairing, and SSE lifecycle.

Faithful port of ``src/relay/stream.ts``, minus the OpenClaw runtime coupling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .models import InboundMessage
from .session import DEFAULT_RELAY_URL, create_session
from .session_store import forget_session_token, persist_session_token
from .sse import SSEClientConfig, SSEHandlers, SSESessionInvalidatedError, connect_sse

logger = logging.getLogger(__name__)

DEFAULT_MAX_RETRIES = 10

#: Primary token env var. ``OPENCLAW_TALKCHANNEL_RELAY_TOKEN`` stays supported so
#: an existing OpenClaw setup keeps working without re-pairing.
RELAY_TOKEN_ENV = "KAKAO_RELAY_TOKEN"
LEGACY_RELAY_TOKEN_ENV = "OPENCLAW_TALKCHANNEL_RELAY_TOKEN"

_TOKEN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"Authorization:\s*Bearer\s+[^\s,;]+", re.IGNORECASE), "Authorization: ***"),
    (re.compile(r"Bearer\s+[^\s,;]+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"sessionToken=[^&\s]+", re.IGNORECASE), "sessionToken=***"),
    (re.compile(r"(?<!session)token=[^&\s]+", re.IGNORECASE), "token=***"),
)


def sanitize_token_from_log(message: str) -> str:
    """Redact bearer tokens before anything reaches the log."""
    for pattern, replacement in _TOKEN_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


@dataclass
class StreamCallbacks:
    on_pairing_required: Callable[[str, int], None] | None = None
    on_pairing_complete: Callable[[str], None] | None = None
    on_pairing_expired: Callable[[str], None] | None = None
    on_token_resolved: Callable[[str, str], None] | None = None
    on_session_invalidated: Callable[[int], None] | None = None
    on_connected: Callable[[], None] | None = None
    on_disconnected: Callable[[], None] | None = None


@dataclass(frozen=True)
class ResolvedToken:
    token: str
    relay_url: str
    is_new_session: bool


async def resolve_token(
    config: Any,
    callbacks: StreamCallbacks,
) -> ResolvedToken:
    """Resolve a relay token, creating a new pairing session as a last resort.

    Order (matching the original, with the legacy env var appended):
    session_token → relay_token → ``KAKAO_RELAY_TOKEN`` →
    ``OPENCLAW_TALKCHANNEL_RELAY_TOKEN`` → ``create_session()``.
    """
    relay_url = config.relay_url or DEFAULT_RELAY_URL

    if config.session_token:
        return ResolvedToken(config.session_token, relay_url, is_new_session=False)
    if config.relay_token:
        return ResolvedToken(config.relay_token, relay_url, is_new_session=False)

    for env_name in (RELAY_TOKEN_ENV, LEGACY_RELAY_TOKEN_ENV):
        env_token = os.environ.get(env_name)
        if env_token:
            return ResolvedToken(env_token, relay_url, is_new_session=False)

    result = await create_session(relay_url)
    if not result.ok or result.data is None:
        detail = result.error.message if result.error else "Unknown error"
        raise RuntimeError(f"Failed to create session: {detail}")

    if callbacks.on_pairing_required:
        callbacks.on_pairing_required(result.data.pairing_code, result.data.expires_in)

    return ResolvedToken(result.data.session_token, relay_url, is_new_session=True)


async def start_relay_stream(
    config: Any,
    on_message: Callable[[InboundMessage], Awaitable[None]],
    stop_event: asyncio.Event,
    callbacks: StreamCallbacks | None = None,
    max_retries: int = DEFAULT_MAX_RETRIES,
    channel_id: str = "default",
) -> None:
    """Resolve a token then run the SSE stream until ``stop_event`` is set."""
    callbacks = callbacks or StreamCallbacks()

    logger.info("[kakao:%s] Resolving token...", channel_id)
    resolved = await resolve_token(config, callbacks)
    logger.info(
        "[kakao:%s] Token resolved (newSession=%s)", channel_id, resolved.is_new_session
    )

    if callbacks.on_token_resolved:
        callbacks.on_token_resolved(resolved.token, resolved.relay_url)

    def handle_connected() -> None:
        logger.info("[kakao:%s] SSE connected to %s", channel_id, resolved.relay_url)
        if callbacks.on_connected:
            callbacks.on_connected()

    def handle_error(error: Exception) -> None:
        logger.warning("[kakao:%s] SSE error: %s", channel_id, sanitize_token_from_log(str(error)))

    def handle_reconnect(attempt: int) -> None:
        logger.info("[kakao:%s] SSE reconnecting (attempt %s/%s)", channel_id, attempt, max_retries)

    def handle_pairing_complete(data: dict[str, Any]) -> None:
        kakao_user_id = data.get("kakaoUserId", "")
        logger.info("[kakao:%s] Pairing complete: %s", channel_id, kakao_user_id)
        # Only persist once pairing succeeded — see session_store's contract.
        persist_session_token(resolved.token, channel_id)
        if callbacks.on_pairing_complete:
            callbacks.on_pairing_complete(kakao_user_id)

    def handle_pairing_expired(reason: str) -> None:
        logger.warning("[kakao:%s] Pairing expired: %s", channel_id, reason)
        if callbacks.on_pairing_expired:
            callbacks.on_pairing_expired(reason)

    def handle_session_invalidated(status: int) -> None:
        logger.warning("[kakao:%s] Session invalidated: HTTP %s", channel_id, status)
        forget_session_token(channel_id)
        if callbacks.on_session_invalidated:
            callbacks.on_session_invalidated(status)

    handlers = SSEHandlers(
        on_message=on_message,
        on_error=handle_error,
        on_reconnect=handle_reconnect,
        on_connected=handle_connected,
        on_disconnected=callbacks.on_disconnected,
        on_pairing_complete=handle_pairing_complete,
        on_pairing_expired=handle_pairing_expired,
        on_session_invalidated=handle_session_invalidated,
    )

    sse_config = SSEClientConfig(
        relay_url=resolved.relay_url,
        session_token=resolved.token,
        reconnect_delay_ms=getattr(config, "reconnect_delay_ms", None),
        max_reconnect_delay_ms=getattr(config, "max_reconnect_delay_ms", None),
        max_retries=max_retries,
        # AS-IS: timeout_ms is never passed, so the 300s SSE default applies.
    )

    try:
        await connect_sse(sse_config, handlers, stop_event)
    except SSESessionInvalidatedError:
        # Already logged and the stored token already dropped; let the adapter
        # decide whether to restart with a fresh pairing.
        raise
