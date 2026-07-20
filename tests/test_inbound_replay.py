"""One relay message must start at most one agent turn.

Observed on a live gateway 2026-07-20: the relay created a single inbound
message and the adapter handed it to the core 94 times inside one second. Two
faults multiplied — a clean SSE close reconnected with no delay, and the relay
re-flushes queued messages on every subscribe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from hermes_kakao_talkchannel.adapter import KakaoAdapter
from hermes_kakao_talkchannel.transport.models import InboundMessage
from hermes_kakao_talkchannel.transport.sse import (
    CLEAN_CLOSE_RECONNECT_DELAY_SECONDS,
    _sleep,
)
from tests.fixtures.payloads import inbound_wire


@dataclass
class FakePlatformConfig:
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@pytest.fixture()
def adapter(isolated_state_dir: Any) -> KakaoAdapter:
    instance = KakaoAdapter(FakePlatformConfig(extra={"relay_url": "https://relay.example/"}))
    instance._relay_token = "tok-test"
    return instance


@pytest.fixture()
def turns(adapter: KakaoAdapter) -> list[Any]:
    started: list[Any] = []

    async def handler(event: Any) -> None:
        started.append(event)

    adapter.set_message_handler(handler)
    return started


class TestReplayGuard:
    async def test_a_replayed_message_starts_no_second_turn(
        self, adapter: KakaoAdapter, turns: list[Any]
    ) -> None:
        message = InboundMessage.from_wire(inbound_wire())

        for _ in range(94):
            await adapter._on_inbound_message(message)

        assert len(turns) == 1

    async def test_a_replay_does_not_queue_another_callback(
        self, adapter: KakaoAdapter, turns: list[Any]
    ) -> None:
        # Otherwise the reply queue fills with ids whose callbacks are all the
        # same spent one.
        message = InboundMessage.from_wire(inbound_wire())

        await adapter._on_inbound_message(message)
        await adapter._on_inbound_message(message)

        assert len(adapter._pending_message_ids["botuserkey-abc123"]) == 1

    async def test_distinct_messages_each_start_a_turn(
        self, adapter: KakaoAdapter, turns: list[Any]
    ) -> None:
        await adapter._on_inbound_message(
            InboundMessage.from_wire(inbound_wire(id="msg-a"))
        )
        await adapter._on_inbound_message(
            InboundMessage.from_wire(inbound_wire(id="msg-b"))
        )

        assert len(turns) == 2

    async def test_the_guard_does_not_grow_without_bound(
        self, adapter: KakaoAdapter, turns: list[Any]
    ) -> None:
        for index in range(600):
            await adapter._on_inbound_message(
                InboundMessage.from_wire(inbound_wire(id=f"msg-{index}"))
            )

        assert len(adapter._seen_message_ids) <= 500


class TestCleanCloseBackoff:
    def test_there_is_a_delay(self) -> None:
        # Zero would restore the tight reconnect loop.
        assert CLEAN_CLOSE_RECONNECT_DELAY_SECONDS > 0

    async def test_the_delay_is_interruptible(self) -> None:
        # Shutdown must not wait out the backoff.
        stop = asyncio.Event()
        stop.set()

        await asyncio.wait_for(_sleep(60.0, stop), timeout=1.0)
