from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from hermes_kakao_talkchannel.pairing.registry import PairingSnapshot
from hermes_kakao_talkchannel.pairing.state_file import (
    REQUEST_FILE,
    STATE_FILE,
    PairingStateFile,
    clear_pairing_request,
    clear_pairing_state,
    consume_pairing_request,
    describe_staleness,
    read_pairing_state,
    resolve_state_dir,
    write_pairing_request,
    write_pairing_state,
)


def snapshot(**overrides: object) -> PairingSnapshot:
    base = {
        "account_id": "default",
        "channel_id": "default",
        "state": "pending",
        "pairing_code": "CODE-1234",
        "expires_at": time.time() + 300,
        "expires_in_seconds": 300,
        "issued_at": time.time(),
        "paired_user_id": None,
        "paired_at": None,
        "can_reissue": True,
        "reissue_blocked_reason": None,
    }
    base.update(overrides)
    return PairingSnapshot(**base)  # type: ignore[arg-type]


def state(**overrides: object) -> PairingStateFile:
    base = {"pid": os.getpid(), "updated_at": time.time(), "accounts": []}
    base.update(overrides)
    return PairingStateFile(**base)  # type: ignore[arg-type]


class TestLocation:
    def test_lives_under_hermes_home(self, isolated_state_dir: Path) -> None:
        assert resolve_state_dir() == isolated_state_dir / "kakao-talkchannel"


class TestState:
    def test_round_trips(self, isolated_state_dir: Path) -> None:
        write_pairing_state([snapshot()])
        loaded = read_pairing_state()

        assert loaded is not None
        assert loaded.accounts[0].pairing_code == "CODE-1234"
        assert loaded.pid == os.getpid()

    def test_absent_is_none(self, isolated_state_dir: Path) -> None:
        assert read_pairing_state() is None

    def test_corrupt_is_none_not_an_exception(self, isolated_state_dir: Path) -> None:
        target = resolve_state_dir() / STATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ not json", encoding="utf-8")

        assert read_pairing_state() is None

    def test_missing_keys_are_none_not_an_exception(self, isolated_state_dir: Path) -> None:
        target = resolve_state_dir() / STATE_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"accounts": []}), encoding="utf-8")

        assert read_pairing_state() is None

    def test_overwrites_cleanly(self, isolated_state_dir: Path) -> None:
        write_pairing_state([snapshot(pairing_code="CODE-A")])
        write_pairing_state([snapshot(pairing_code="CODE-B")])

        loaded = read_pairing_state()
        assert loaded is not None
        assert len(loaded.accounts) == 1
        assert loaded.accounts[0].pairing_code == "CODE-B"

    def test_leaves_no_temp_files(self, isolated_state_dir: Path) -> None:
        write_pairing_state([snapshot()])
        leftovers = [p for p in resolve_state_dir().iterdir() if p.suffix == ".tmp"]
        assert leftovers == []

    def test_clears(self, isolated_state_dir: Path) -> None:
        write_pairing_state([snapshot()])
        clear_pairing_state()
        assert read_pairing_state() is None

    def test_clearing_twice_does_not_raise(self, isolated_state_dir: Path) -> None:
        clear_pairing_state()
        clear_pairing_state()

    @pytest.mark.skipif(os.name == "nt", reason="chmod is a no-op on Windows")
    def test_is_owner_only(self, isolated_state_dir: Path) -> None:
        write_pairing_state([snapshot()])
        mode = (resolve_state_dir() / STATE_FILE).stat().st_mode & 0o777
        assert mode == 0o600


class TestStaleness:
    def test_fresh_file_from_a_live_writer_is_fine(self, isolated_state_dir: Path) -> None:
        assert describe_staleness(state()).stale is False

    def test_quiet_file_is_tolerated_while_its_writer_lives(self) -> None:
        # Publishing is event-driven plus a heartbeat; minutes of silence is
        # normal for a stable pairing and must not read as death.
        assert describe_staleness(state(updated_at=time.time() - 120)).stale is False

    def test_reports_writer_gone_only_after_checking_the_pid(self) -> None:
        result = describe_staleness(state(pid=0))
        assert result.stale is True
        assert result.reason == "writer-gone"

    def test_reports_too_old_when_the_writer_is_alive(self) -> None:
        # The OpenClaw version short-circuited on age and never checked the pid,
        # while its message claimed the process was dead. That false detail cost
        # a real investigation on a live VM.
        result = describe_staleness(state(updated_at=time.time() - 20 * 60))
        assert result.stale is True
        assert result.reason == "too-old"
        assert result.reason != "writer-gone"

    def test_not_stale_carries_no_reason(self) -> None:
        assert describe_staleness(state()).reason is None

    def test_always_reports_the_age(self) -> None:
        assert describe_staleness(state(updated_at=time.time() - 5)).age_seconds >= 5


class TestRequest:
    def test_round_trips_and_is_consumed_once(self, isolated_state_dir: Path) -> None:
        written = write_pairing_request("acct", 5.0)

        consumed = consume_pairing_request()
        assert consumed is not None
        assert consumed.id == written.id
        assert consumed.account_id == "acct"
        assert consumed.timeout_seconds == 5.0

        # Consuming deletes it, so a request cannot be replayed.
        assert consume_pairing_request() is None

    def test_nothing_pending_is_none(self, isolated_state_dir: Path) -> None:
        assert consume_pairing_request() is None

    def test_no_account_id_when_none_given(self, isolated_state_dir: Path) -> None:
        write_pairing_request(None, 1.0)
        assert consume_pairing_request().account_id is None

    def test_clears_without_consuming(self, isolated_state_dir: Path) -> None:
        write_pairing_request("acct", 1.0)
        clear_pairing_request()
        assert not (resolve_state_dir() / REQUEST_FILE).exists()

    def test_corrupt_request_is_removed_rather_than_looping_forever(
        self, isolated_state_dir: Path
    ) -> None:
        target = resolve_state_dir() / REQUEST_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("{ not json", encoding="utf-8")

        assert consume_pairing_request() is None
        assert not target.exists()
