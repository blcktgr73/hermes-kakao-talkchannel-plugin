"""KakaoTalk skill callback delivery and expiry tracking.

Faithful port of ``src/kakao/callback.ts``.

Kakao callbacks are single-use and expire roughly one minute after the skill
request. Like the original, this module does **not** compute ``expires_at`` — the
caller sets it (``time.time() * 1000 + 60000``).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import aiohttp


@dataclass
class PendingCallback:
    callback_url: str
    expires_at: float  # milliseconds since epoch
    message_id: str


@dataclass(frozen=True)
class CallbackResult:
    success: bool
    error: str | None = None


def _now_ms() -> float:
    return time.time() * 1000


async def send_callback(callback_url: str, response: dict[str, Any]) -> CallbackResult:
    """POST a skill response to Kakao's callback URL. Never raises.

    Ported as-is: no Authorization header, no retry, and no explicit timeout.
    See docs/known-relay-defects.md (D6).
    """
    try:
        async with aiohttp.ClientSession() as session, session.post(
            callback_url,
            json=response,
            headers={"Content-Type": "application/json"},
        ) as http_response:
            if http_response.status < 200 or http_response.status >= 300:
                return CallbackResult(success=False, error=f"HTTP {http_response.status}")
            return CallbackResult(success=True)
    except Exception as error:  # noqa: BLE001 - mirrors the original catch-all
        return CallbackResult(success=False, error=str(error) or "Unknown error")


def is_callback_expired(callback: PendingCallback) -> bool:
    return _now_ms() >= callback.expires_at


class CallbackTracker:
    """In-memory registry of pending callbacks, keyed by message id.

    There is no automatic timer; call :meth:`cleanup` periodically.
    """

    def __init__(self) -> None:
        self._callbacks: dict[str, PendingCallback] = {}

    def add(self, callback: PendingCallback) -> None:
        """Register a callback, overwriting any entry with the same message id."""
        self._callbacks[callback.message_id] = callback

    def get(self, message_id: str) -> PendingCallback | None:
        return self._callbacks.get(message_id)

    def remove(self, message_id: str) -> None:
        self._callbacks.pop(message_id, None)

    def cleanup(self) -> None:
        """Drop every expired entry."""
        now = _now_ms()
        expired = [key for key, cb in self._callbacks.items() if cb.expires_at <= now]
        for key in expired:
            del self._callbacks[key]

    def __len__(self) -> int:
        return len(self._callbacks)


def create_callback_tracker() -> CallbackTracker:
    return CallbackTracker()
