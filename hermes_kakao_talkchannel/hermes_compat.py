"""Host imports, with test-time fallbacks.

The exact import path of Hermes' adapter base class is **not verified** — the
plugin SDK research (docs/00-hermes-plugin-sdk.md) read the sources at
``gateway/platforms/base.py`` in the repository, but which top-level package
that lands under once ``hermes-agent`` is pip-installed was never confirmed
against a real install.

So: try the plausible paths in order, and if none resolve, fall back to minimal
local stubs. The stubs exist so the pure-domain and transport test suites run on
a machine with no Hermes installed. :data:`HERMES_AVAILABLE` records which
happened, and ``registration.check_requirements`` refuses to start a real
gateway when the stubs are in play.

Resolving this properly is tracked as open question Q8 in
docs/03-implementation-plan.md — verify against an actual install before
claiming the adapter works end to end.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

_CANDIDATE_MODULES = (
    "hermes_agent.gateway.platforms.base",
    "hermes.gateway.platforms.base",
    "gateway.platforms.base",
)

HERMES_AVAILABLE = False
HERMES_BASE_MODULE: str | None = None

BasePlatformAdapter: Any = None
MessageEvent: Any = None
MessageType: Any = None
SendResult: Any = None
Platform: Any = None


def _try_import_host() -> bool:
    global BasePlatformAdapter, MessageEvent, MessageType, SendResult, Platform
    global HERMES_AVAILABLE, HERMES_BASE_MODULE

    import importlib

    for module_name in _CANDIDATE_MODULES:
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue

        try:
            BasePlatformAdapter = module.BasePlatformAdapter
            MessageEvent = module.MessageEvent
            MessageType = module.MessageType
            SendResult = module.SendResult
        except AttributeError as error:
            logger.warning(
                "Found %s but it lacks an expected symbol (%s); trying next candidate",
                module_name,
                error,
            )
            continue

        Platform = getattr(module, "Platform", None)
        if Platform is None:
            for platform_module in ("hermes_agent.gateway.types", "gateway.types"):
                try:
                    Platform = importlib.import_module(platform_module).Platform
                    break
                except (ImportError, AttributeError):
                    continue

        HERMES_AVAILABLE = True
        HERMES_BASE_MODULE = module_name
        logger.debug("Resolved Hermes platform base from %s", module_name)
        return True

    return False


# ---------------------------------------------------------------------------
# Fallback stubs — test scaffolding only, never a runtime substitute.
# ---------------------------------------------------------------------------


class _StubMessageType(StrEnum):
    TEXT = "text"
    LOCATION = "location"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    VOICE = "voice"
    DOCUMENT = "document"
    STICKER = "sticker"
    COMMAND = "command"


@dataclass
class _StubSessionSource:
    platform: str = ""
    chat_id: str = ""
    chat_name: str = ""
    chat_type: str = "dm"
    user_id: str = ""
    user_name: str = ""
    thread_id: str | None = None


@dataclass
class _StubMessageEvent:
    text: str = ""
    message_type: Any = _StubMessageType.TEXT
    source: Any = None
    raw_message: Any = None
    message_id: str | None = None
    media_urls: list[str] = field(default_factory=list)
    media_types: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float | None = None


@dataclass
class _StubSendResult:
    success: bool = False
    message_id: str | None = None
    error: str | None = None
    raw_response: Any = None
    retryable: bool = False
    retry_after: float | None = None


class _StubBasePlatformAdapter:
    """Minimal stand-in mirroring the parts of the real base class we rely on."""

    REQUIRES_EDIT_FINALIZE = False

    def __init__(self, config: Any, platform: Any = None) -> None:
        self.config = config
        self.platform = platform
        self._connected = False
        self._fatal_error: tuple[str, str, bool] | None = None
        self._message_handler: Any = None

    def build_source(self, **kwargs: Any) -> Any:
        return _StubSessionSource(**kwargs)

    async def handle_message(self, event: Any) -> Any:
        if self._message_handler is None:
            return None
        return await self._message_handler(event)

    def set_message_handler(self, handler: Any) -> None:
        self._message_handler = handler

    def _mark_connected(self) -> None:
        self._connected = True

    def _mark_disconnected(self) -> None:
        self._connected = False

    def _set_fatal_error(self, code: str, message: str, *, retryable: bool = False) -> None:
        self._fatal_error = (code, message, retryable)


if not _try_import_host():
    logger.debug("Hermes not importable; using local stubs (tests only)")
    BasePlatformAdapter = _StubBasePlatformAdapter
    MessageEvent = _StubMessageEvent
    MessageType = _StubMessageType
    SendResult = _StubSendResult
    Platform = None

SessionSource = _StubSessionSource

__all__ = [
    "HERMES_AVAILABLE",
    "HERMES_BASE_MODULE",
    "BasePlatformAdapter",
    "MessageEvent",
    "MessageType",
    "Platform",
    "SendResult",
    "SessionSource",
]
