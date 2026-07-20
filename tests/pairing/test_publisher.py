from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hermes_kakao_talkchannel.pairing import publisher as publisher_module
from hermes_kakao_talkchannel.pairing.publisher import PairingPublisher
from hermes_kakao_talkchannel.pairing.registry import (
    PairingSnapshot,
    record_pairing_required,
    register_account,
    reset_pairing_registry,
)
from hermes_kakao_talkchannel.pairing.state_file import (
    REQUEST_FILE,
    read_pairing_state,
    resolve_state_dir,
    write_pairing_request,
)


class FakeController:
    """Stands in for the adapter; records what the publisher asked for."""

    def __init__(self) -> None:
        self.requests: list[float] = []

    def reissue_blocked_reason(self) -> str | None:
        return None

    async def request_new_pairing(self, timeout_seconds: float) -> PairingSnapshot:
        self.requests.append(timeout_seconds)
        return record_pairing_required("default", "default", "CODE-FRESH", 300)


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    reset_pairing_registry()


@pytest.fixture()
async def publisher(isolated_state_dir: Path):
    instance = PairingPublisher()
    yield instance
    await instance.stop()


class TestPublishing:
    async def test_publishes_immediately_on_start(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        record_pairing_required("default", "default", "CODE-1234", 300)
        publisher.start()

        state = read_pairing_state()
        assert state is not None
        assert state.accounts[0].pairing_code == "CODE-1234"

    async def test_republishes_on_every_registry_change(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        publisher.start()
        record_pairing_required("default", "default", "CODE-NEW", 300)

        state = read_pairing_state()
        assert state is not None
        assert state.accounts[0].pairing_code == "CODE-NEW"

    async def test_start_is_idempotent(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        publisher.start()
        publisher.start()

        assert read_pairing_state() is not None

    async def test_stop_removes_the_state_file(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        publisher.start()
        assert read_pairing_state() is not None

        await publisher.stop()
        assert read_pairing_state() is None

    async def test_stop_is_safe_before_start(self, publisher: PairingPublisher) -> None:
        await publisher.stop()

    async def test_a_publish_failure_does_not_propagate(
        self,
        publisher: PairingPublisher,
        isolated_state_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def boom(_accounts: object) -> None:
            raise OSError("disk on fire")

        monkeypatch.setattr(publisher_module, "write_pairing_state", boom)

        # Publishing is best effort; it must never break the pairing flow.
        publisher.start()
        record_pairing_required("default", "default", "CODE-1234", 300)


class TestRequestConsumption:
    async def test_drops_a_request_left_from_a_previous_process(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        # A request written while the gateway was down refers to a gateway that
        # no longer exists; honouring it later would issue a code nobody asked
        # for. Same class of bug as Hermes' NS-570 stale marker.
        write_pairing_request(None, 5.0)

        publisher.start()

        assert not (resolve_state_dir() / REQUEST_FILE).exists()

    async def test_honours_a_request_written_while_running(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        controller = FakeController()
        register_account("default", "default", controller)
        publisher.start()

        write_pairing_request(None, 7.0)

        async def picked_up() -> bool:
            for _ in range(40):
                if controller.requests:
                    return True
                await asyncio.sleep(0.1)
            return False

        assert await picked_up()
        assert controller.requests == [7.0]

        state = read_pairing_state()
        assert state is not None
        assert state.accounts[0].pairing_code == "CODE-FRESH"

    async def test_a_failing_reissue_is_logged_not_raised(
        self, publisher: PairingPublisher, isolated_state_dir: Path
    ) -> None:
        class Failing(FakeController):
            async def request_new_pairing(self, timeout_seconds: float) -> PairingSnapshot:
                raise RuntimeError("relay unreachable")

        register_account("default", "default", Failing())
        publisher.start()
        write_pairing_request(None, 1.0)

        # The CLI detects this by timing out; the loop must keep running.
        await asyncio.sleep(1.5)
        assert not (resolve_state_dir() / REQUEST_FILE).exists()
