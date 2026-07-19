"""Relay transport for the KakaoTalk channel.

Everything here speaks the relay's wire protocol (docs/relay-wire-protocol.md) and
knows nothing about Hermes. A future direct-webhook transport would slot in
alongside ``relay.py`` behind the same ``start_relay_stream``/``send_reply`` pair.
"""

from __future__ import annotations

from .client import (
    DEFAULT_TIMEOUT_MS,
    RelayClientConfig,
    RelayHttpError,
    health_check,
    parse_error_body,
    send_reply,
)
from .models import (
    CreateSessionResponse,
    HealthResult,
    InboundMessage,
    NormalizedMessage,
    RelayError,
    SendReplyResponse,
    SessionStatusResponse,
    SSEEvent,
)
from .relay import (
    LEGACY_RELAY_TOKEN_ENV,
    RELAY_TOKEN_ENV,
    ResolvedToken,
    StreamCallbacks,
    resolve_token,
    sanitize_token_from_log,
    start_relay_stream,
)
from .session import (
    DEFAULT_RELAY_URL,
    RelayResult,
    check_session_status,
    create_session,
    normalize_relay_url,
)
from .session_store import forget_session_token, load_session_token, persist_session_token
from .sse import (
    SSEClientConfig,
    SSEHandlers,
    SSESessionInvalidatedError,
    calculate_reconnect_delay,
    connect_sse,
    parse_sse_chunk,
)

__all__ = [
    "DEFAULT_RELAY_URL",
    "DEFAULT_TIMEOUT_MS",
    "LEGACY_RELAY_TOKEN_ENV",
    "RELAY_TOKEN_ENV",
    "CreateSessionResponse",
    "HealthResult",
    "InboundMessage",
    "NormalizedMessage",
    "RelayClientConfig",
    "RelayError",
    "RelayHttpError",
    "RelayResult",
    "ResolvedToken",
    "SSEClientConfig",
    "SSEEvent",
    "SSEHandlers",
    "SSESessionInvalidatedError",
    "SendReplyResponse",
    "SessionStatusResponse",
    "StreamCallbacks",
    "calculate_reconnect_delay",
    "check_session_status",
    "connect_sse",
    "create_session",
    "forget_session_token",
    "health_check",
    "load_session_token",
    "normalize_relay_url",
    "parse_error_body",
    "parse_sse_chunk",
    "persist_session_token",
    "resolve_token",
    "sanitize_token_from_log",
    "send_reply",
    "start_relay_stream",
]
