"""Gateway-side bridge between the pairing registry and the CLI.

Runs inside the gateway process, as an asyncio task started from the adapter's
``connect()``. Two jobs:

1. Publish every registry change to ``pairing-state.json`` so
   ``hermes kakao pairing status`` can read it from a separate process, plus a
   heartbeat so the file stays fresh while nothing changes.
2. Poll ``pairing-request.json`` so ``hermes kakao pairing new`` can ask this
   process to re-issue a code.

Polling rather than file watching mirrors ``gateway/run.py``'s
``_drain_control_watcher``, which is Hermes' own marker-consumption loop — no
watcher-leak failure mode, and a missed tick costs a second.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from .registry import list_pairing_snapshots, on_pairing_change, request_new_pairing
from .state_file import (
    clear_pairing_request,
    clear_pairing_state,
    consume_pairing_request,
    write_pairing_state,
)

logger = logging.getLogger(__name__)

REQUEST_POLL_INTERVAL_SECONDS = 1.0

#: How often the state file is refreshed even when nothing has changed.
#:
#: Publishing is otherwise event-driven, so a stable paired account would never
#: rewrite the file and its ``updatedAt`` would age indefinitely. The CLI's age
#: backstop needs a heartbeat to mean anything — without one, a healthy gateway
#: reads as dead, which is exactly what happened in OpenClaw before this existed.
HEARTBEAT_INTERVAL_SECONDS = 30.0


class PairingPublisher:
    """Publishes pairing state and consumes CLI re-issue requests."""

    def __init__(self) -> None:
        self._unsubscribe: object | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is not None:
            return

        # A request written while this process was down refers to a gateway that
        # no longer exists. Honouring it later would re-issue a code nobody
        # asked for — the same class of bug as Hermes' NS-570 stale marker.
        clear_pairing_request()

        self._publish()
        self._unsubscribe = on_pairing_change(self._publish)
        self._stopping = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="kakao-pairing-publisher")

    async def stop(self) -> None:
        self._stopping.set()

        unsubscribe = self._unsubscribe
        if callable(unsubscribe):
            unsubscribe()
        self._unsubscribe = None

        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        clear_pairing_state()
        clear_pairing_request()

    # -- internals ---------------------------------------------------------

    def _publish(self) -> None:
        try:
            write_pairing_state(list_pairing_snapshots())
        except Exception as error:  # noqa: BLE001
            logger.warning("[kakao] Could not publish pairing state: %s", error)

    async def _run(self) -> None:
        elapsed_since_heartbeat = 0.0

        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=REQUEST_POLL_INTERVAL_SECONDS
                )
                return  # stop() was called
            except TimeoutError:
                pass

            await self._poll_request()

            elapsed_since_heartbeat += REQUEST_POLL_INTERVAL_SECONDS
            if elapsed_since_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                elapsed_since_heartbeat = 0.0
                self._publish()

    async def _poll_request(self) -> None:
        try:
            request = consume_pairing_request()
        except Exception as error:  # noqa: BLE001
            logger.warning("[kakao] Could not read pairing request: %s", error)
            return
        if request is None:
            return

        logger.info("[kakao] Re-issue requested via CLI (request %s)", request.id)

        try:
            await request_new_pairing(request.account_id, request.timeout_seconds)
            # request_new_pairing resolves once the code exists and
            # record_pairing_required has already published; publishing again is
            # harmless insurance.
            self._publish()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001
            # The CLI detects this by timing out; the reason is here in the log.
            logger.warning("[kakao] CLI re-issue failed: %s", error)
