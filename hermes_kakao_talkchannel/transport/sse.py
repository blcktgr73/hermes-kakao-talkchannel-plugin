"""SSE client for the relay's inbound message stream.

Faithful port of ``src/relay/sse.ts``. Several known defects are reproduced
deliberately so behaviour matches the working OpenClaw plugin; each is marked
``AS-IS`` and catalogued in docs/known-relay-defects.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp

from .models import InboundMessage, ParsedChunk, SSEEvent

logger = logging.getLogger(__name__)

DEFAULT_RECONNECT_DELAY_MS = 1000
DEFAULT_MAX_RECONNECT_DELAY_MS = 30000
DEFAULT_TIMEOUT_MS = 300000  # 5 minutes, per connection attempt


@dataclass
class _EventCursor:
    """Mutable holder for the SSE resume cursor, shared across reconnects."""

    last_event_id: str | None = None


class SSESessionInvalidatedError(Exception):
    """Raised on HTTP 401/410 — the session token is dead and must be re-issued."""

    def __init__(self, status: int) -> None:
        super().__init__(f"SSE session invalidated: HTTP {status}")
        self.status = status


@dataclass
class SSEClientConfig:
    relay_url: str
    relay_token: str | None = None
    session_token: str | None = None
    reconnect_delay_ms: int | None = None
    max_reconnect_delay_ms: int | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None


@dataclass
class SSEHandlers:
    on_message: Callable[[InboundMessage], Awaitable[None]]
    on_error: Callable[[Exception], None] | None = None
    on_reconnect: Callable[[int], None] | None = None
    on_connected: Callable[[], None] | None = None
    on_disconnected: Callable[[], None] | None = None
    on_pairing_complete: Callable[[dict[str, Any]], None] | None = None
    on_pairing_expired: Callable[[str], None] | None = None
    on_session_invalidated: Callable[[int], None] | None = None


def calculate_reconnect_delay(attempt: int, base_delay_ms: int, max_delay_ms: int) -> int:
    """Exponential backoff with additive jitter.

    AS-IS (D3): jitter is added *after* the cap, so the result can exceed
    ``max_delay_ms`` by up to 20%. Callers pass an already-incremented attempt,
    so the first retry uses ``attempt=1``.
    """
    exponential_delay = base_delay_ms * (2**attempt)
    capped_delay = min(exponential_delay, max_delay_ms)
    jitter = capped_delay * 0.2 * random.random()
    return math.floor(capped_delay + jitter)


def parse_sse_chunk(chunk: str) -> ParsedChunk:
    """Parse complete SSE events out of a buffer.

    AS-IS (D5): only the last ``data:`` line of a block is kept, so multi-line
    ``data:`` fields (which the SSE spec says to join with newlines) are
    truncated. Events lacking either an ``event:`` name or a ``data:`` body are
    dropped silently and do not count as parse errors.
    """
    events: list[SSEEvent] = []
    consumed = 0
    parse_errors = 0
    search_from = 0

    while True:
        boundary = chunk.find("\n\n", search_from)
        if boundary == -1:
            break

        block = chunk[consumed:boundary]
        end_pos = boundary + 2

        event_name: str | None = None
        data_line: str | None = None
        event_id: str | None = None

        for line in block.split("\n"):
            if line == "":
                continue
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_line = line[5:].strip()
            elif line.startswith("id:"):
                event_id = line[3:].strip()

        if event_name and data_line:
            try:
                events.append(
                    SSEEvent(event=event_name, data=json.loads(data_line), id=event_id)  # type: ignore[arg-type]
                )
            except json.JSONDecodeError:
                parse_errors += 1

        consumed = end_pos
        search_from = end_pos

    return ParsedChunk(events=events, consumed=consumed, parse_errors=parse_errors)


def _normalize_base_url(relay_url: str) -> str:
    return relay_url if relay_url.endswith("/") else relay_url + "/"


async def connect_sse(
    config: SSEClientConfig,
    handlers: SSEHandlers,
    stop_event: asyncio.Event,
) -> None:
    """Subscribe to the relay event stream, reconnecting until ``stop_event`` is set.

    Raises :class:`SSESessionInvalidatedError` (no reconnect) when the relay
    rejects the token, and ``RuntimeError`` when ``max_retries`` is exhausted.
    """
    reconnect_delay_ms = config.reconnect_delay_ms or DEFAULT_RECONNECT_DELAY_MS
    max_reconnect_delay_ms = config.max_reconnect_delay_ms or DEFAULT_MAX_RECONNECT_DELAY_MS
    timeout_ms = config.timeout_ms or DEFAULT_TIMEOUT_MS

    token = config.session_token or config.relay_token
    if not token:
        raise ValueError("SSE connection requires sessionToken or relayToken")

    reconnect_attempt = 0
    # Single-slot mutable cursor: the read loop advances it, the reconnect loop
    # reads it back for the Last-Event-ID resume header.
    cursor = _EventCursor()
    url = f"{_normalize_base_url(config.relay_url)}v1/events"

    while not stop_event.is_set():
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache",
            }
            if cursor.last_event_id:
                headers["Last-Event-ID"] = cursor.last_event_id

            # AS-IS (D2): this timeout applies to the whole connection, not to
            # idle time, so a healthy stream is torn down every 5 minutes and
            # reconnects through the error path with backoff.
            timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)

            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, headers=headers) as response,
            ):
                if response.status in (401, 410):
                    if handlers.on_session_invalidated:
                        handlers.on_session_invalidated(response.status)
                    raise SSESessionInvalidatedError(response.status)
                if response.status < 200 or response.status >= 300:
                    # AS-IS: 429 and 5xx get no special handling, no Retry-After.
                    raise RuntimeError(f"SSE connection failed: HTTP {response.status}")

                reconnect_attempt = 0
                if handlers.on_connected:
                    handlers.on_connected()

                await _read_stream(response, handlers, stop_event, cursor)
                # Both a pairing-triggered break and a clean close reconnect
                # immediately, with no backoff and no attempt increment.
                continue

        except SSESessionInvalidatedError as error:
            if stop_event.is_set():
                return
            if handlers.on_error:
                handlers.on_error(error)
            raise

        except Exception as error:  # noqa: BLE001 - mirrors the original catch-all
            if stop_event.is_set():
                return

            if handlers.on_error:
                handlers.on_error(error if isinstance(error, Exception) else Exception(str(error)))
            if handlers.on_disconnected:
                handlers.on_disconnected()

            reconnect_attempt += 1
            if handlers.on_reconnect:
                handlers.on_reconnect(reconnect_attempt)

            if config.max_retries is not None and reconnect_attempt >= config.max_retries:
                raise RuntimeError(
                    f"Max reconnect attempts ({config.max_retries}) exceeded"
                ) from error

            delay = calculate_reconnect_delay(
                reconnect_attempt, reconnect_delay_ms, max_reconnect_delay_ms
            )
            await _sleep(delay / 1000, stop_event)


async def _read_stream(
    response: aiohttp.ClientResponse,
    handlers: SSEHandlers,
    stop_event: asyncio.Event,
    cursor: _EventCursor,
) -> bool:
    """Drain one connection. Returns True when a pairing-triggered reconnect is due."""
    buffer = ""
    reconnect_for_pairing = False

    while not stop_event.is_set():
        raw = await response.content.readany()
        if not raw:
            break

        buffer += raw.decode("utf-8", errors="replace")
        parsed = parse_sse_chunk(buffer)
        if parsed.consumed > 0:
            buffer = buffer[parsed.consumed :]
        if parsed.parse_errors > 0 and handlers.on_error:
            handlers.on_error(
                Exception(f"Skipped {parsed.parse_errors} SSE event(s) with malformed JSON")
            )

        for event in parsed.events:
            # Every event type advances the resume cursor, including pings.
            if event.id:
                cursor.last_event_id = event.id

            if event.event == "message":
                try:
                    await handlers.on_message(InboundMessage.from_wire(event.data))
                except Exception as error:  # noqa: BLE001
                    # A failing handler must not drop the connection.
                    if handlers.on_error:
                        handlers.on_error(error)
            elif event.event == "error":
                if handlers.on_error:
                    handlers.on_error(Exception(event.data.get("message", "Unknown relay error")))
            elif event.event == "pairing_complete":
                if handlers.on_pairing_complete:
                    handlers.on_pairing_complete(event.data)
                reconnect_for_pairing = True
            elif event.event == "pairing_expired" and handlers.on_pairing_expired:
                handlers.on_pairing_expired(event.data.get("reason", "unknown"))
            # AS-IS (D4): "ping" has no branch and there is no idle watchdog.

        if reconnect_for_pairing:
            # Break only after draining the whole chunk, matching the original.
            break

    return reconnect_for_pairing


async def _sleep(seconds: float, stop_event: asyncio.Event) -> None:
    """Sleep, waking early if ``stop_event`` is set."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=seconds)
    except TimeoutError:
        return
