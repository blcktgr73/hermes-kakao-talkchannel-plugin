"""Pairing registry tests.

Locks the three properties the registry exists to guarantee: non-destructive
reads, cleanup on terminal states, and deduplication of the repeated
``pairing_complete`` events the relay sends.
"""

from __future__ import annotations

import time

import pytest

from hermes_kakao_talkchannel.pairing.registry import (
    PairingSnapshot,
    add_pairing_waiter,
    get_pairing_snapshot,
    list_pairing_snapshots,
    on_pairing_change,
    record_pairing_complete,
    record_pairing_expired,
    record_pairing_required,
    record_session_invalidated,
    record_session_reused,
    register_account,
    request_new_pairing,
    reset_pairing_registry,
    unregister_account,
)

ACCOUNT = "default"


class FakeController:
    def __init__(self, blocked: str | None = None) -> None:
        self.blocked = blocked
        self.calls: list[float] = []

    def reissue_blocked_reason(self) -> str | None:
        return self.blocked

    async def request_new_pairing(self, timeout_seconds: float) -> PairingSnapshot:
        self.calls.append(timeout_seconds)
        return get_pairing_snapshot(ACCOUNT)  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def clean_registry() -> None:
    reset_pairing_registry()


class TestReads:
    def test_unknown_account_is_none(self) -> None:
        assert get_pairing_snapshot("nope") is None

    def test_reads_are_non_destructive(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)

        for _ in range(3):
            assert get_pairing_snapshot(ACCOUNT).pairing_code == "CODE-1234"

    def test_falls_back_to_the_first_account(self) -> None:
        record_pairing_required("first", "first", "CODE-A", 300)
        record_pairing_required("second", "second", "CODE-B", 300)

        assert get_pairing_snapshot().account_id == "first"

    def test_lists_every_account(self) -> None:
        record_pairing_required("a", "a", "CODE-A", 300)
        record_pairing_required("b", "b", "CODE-B", 300)

        assert sorted(s.account_id for s in list_pairing_snapshots()) == ["a", "b"]


class TestTransitions:
    def test_pending_reports_a_countdown(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        assert get_pairing_snapshot(ACCOUNT).expires_in_seconds == pytest.approx(300, abs=2)

    def test_expired_code_is_withheld_without_waiting_for_the_relay(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", -1)

        snapshot = get_pairing_snapshot(ACCOUNT)
        assert snapshot.state == "expired"
        # A dead code must never be handed to an operator.
        assert snapshot.pairing_code is None

    def test_completion_clears_the_code(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        record_pairing_complete(ACCOUNT, ACCOUNT, "kakao-user-1")

        snapshot = get_pairing_snapshot(ACCOUNT)
        assert snapshot.state == "paired"
        assert snapshot.pairing_code is None
        assert snapshot.paired_user_id == "kakao-user-1"

    def test_expiry_clears_the_code(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        record_pairing_expired(ACCOUNT, ACCOUNT)

        snapshot = get_pairing_snapshot(ACCOUNT)
        assert snapshot.state == "expired"
        assert snapshot.pairing_code is None

    def test_reused_session_marks_paired(self) -> None:
        record_session_reused(ACCOUNT, ACCOUNT)
        assert get_pairing_snapshot(ACCOUNT).state == "paired"

    def test_reused_session_does_not_mask_a_pending_code(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        record_session_reused(ACCOUNT, ACCOUNT)

        assert get_pairing_snapshot(ACCOUNT).state == "pending"

    def test_invalidation_drops_paired_state(self) -> None:
        record_pairing_complete(ACCOUNT, ACCOUNT, "kakao-user-1")
        record_session_invalidated(ACCOUNT, ACCOUNT)

        snapshot = get_pairing_snapshot(ACCOUNT)
        assert snapshot.state == "unpaired"
        assert snapshot.paired_user_id is None

    def test_unregister_forgets_everything(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        unregister_account(ACCOUNT)

        assert get_pairing_snapshot(ACCOUNT) is None


class TestCompletionDedupe:
    # The relay delivers this ~4x in 2s.
    def test_only_the_first_completion_is_new(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)

        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is True
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is False
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is False
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is False

    def test_a_different_user_counts_as_new(self) -> None:
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is True
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-2") is True

    def test_a_later_repair_counts_as_new(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is True

        real_time = time.time
        monkeypatch.setattr(time, "time", lambda: real_time() + 30)
        assert record_pairing_complete(ACCOUNT, ACCOUNT, "user-1") is True


class TestCanReissue:
    def test_false_without_a_running_account(self) -> None:
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)

        snapshot = get_pairing_snapshot(ACCOUNT)
        assert snapshot.can_reissue is False
        assert snapshot.reissue_blocked_reason == "account is not running"

    def test_true_for_a_running_account(self) -> None:
        # Regression: a controller returning None means re-issue IS available,
        # which a naive `or` would swallow as "blocked".
        register_account(ACCOUNT, ACCOUNT, FakeController())
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)

        assert get_pairing_snapshot(ACCOUNT).can_reissue is True

    def test_surfaces_the_block_reason(self) -> None:
        register_account(ACCOUNT, ACCOUNT, FakeController("uses a configured relay token"))
        assert get_pairing_snapshot(ACCOUNT).reissue_blocked_reason == (
            "uses a configured relay token"
        )


class TestChangeListeners:
    def test_fire_on_every_mutation(self) -> None:
        calls: list[int] = []
        on_pairing_change(lambda: calls.append(1))

        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        record_pairing_complete(ACCOUNT, ACCOUNT, "user-1")
        record_pairing_expired(ACCOUNT, ACCOUNT)

        assert len(calls) == 3

    def test_a_failing_listener_does_not_break_pairing(self) -> None:
        def boom() -> None:
            raise RuntimeError("publisher exploded")

        on_pairing_change(boom)

        # Must not raise — publishing is best effort.
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        assert get_pairing_snapshot(ACCOUNT).pairing_code == "CODE-1234"

    def test_unsubscribe_stops_delivery(self) -> None:
        calls: list[int] = []
        unsubscribe = on_pairing_change(lambda: calls.append(1))
        unsubscribe()

        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        assert calls == []


class TestWaiters:
    def test_resolve_when_a_code_is_issued(self) -> None:
        seen: list[PairingSnapshot] = []
        add_pairing_waiter(ACCOUNT, seen.append)

        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-LATER", 300)

        assert [s.pairing_code for s in seen] == ["CODE-LATER"]

    def test_resolve_instead_of_hanging_when_the_account_goes_away(self) -> None:
        seen: list[PairingSnapshot] = []
        register_account(ACCOUNT, ACCOUNT, FakeController())
        add_pairing_waiter(ACCOUNT, seen.append)

        unregister_account(ACCOUNT)

        assert len(seen) == 1

    def test_cancel_removes_the_waiter(self) -> None:
        seen: list[PairingSnapshot] = []
        cancel = add_pairing_waiter(ACCOUNT, seen.append)
        cancel()

        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-1234", 300)
        assert seen == []


class TestRequestNewPairing:
    async def test_fails_when_nothing_is_running(self) -> None:
        with pytest.raises(RuntimeError, match="No KakaoTalk account is running"):
            await request_new_pairing(None, 1.0)

    async def test_fails_for_an_unknown_account(self) -> None:
        register_account(ACCOUNT, ACCOUNT, FakeController())
        with pytest.raises(RuntimeError, match="Unknown KakaoTalk account"):
            await request_new_pairing("other", 1.0)

    async def test_fails_when_blocked(self) -> None:
        register_account(ACCOUNT, ACCOUNT, FakeController("uses a configured relay token"))
        with pytest.raises(RuntimeError, match="configured relay token"):
            await request_new_pairing(ACCOUNT, 1.0)

    async def test_delegates_to_the_controller(self) -> None:
        controller = FakeController()
        register_account(ACCOUNT, ACCOUNT, controller)
        record_pairing_required(ACCOUNT, ACCOUNT, "CODE-NEW", 300)

        await request_new_pairing(ACCOUNT, 4.5)

        assert controller.calls == [4.5]
