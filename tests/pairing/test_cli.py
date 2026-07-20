from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from hermes_kakao_talkchannel.pairing.cli import (
    CLI_COMMAND_NAME,
    PairingCliError,
    format_snapshot,
    handle_command,
    register_pairing_cli,
    setup_parser,
    stale_warning,
)
from hermes_kakao_talkchannel.pairing.registry import PairingSnapshot
from hermes_kakao_talkchannel.pairing.state_file import (
    REQUEST_FILE,
    STATE_FILE,
    PairingStateFile,
    describe_staleness,
    resolve_state_dir,
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


def args(**kwargs: Any) -> argparse.Namespace:
    defaults = {"kakao_action": "status", "account": None, "json": False, "timeout": 30.0}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def write_stale_state() -> None:
    """State whose writer pid can never be alive, so it always reads as stale."""
    target = resolve_state_dir() / STATE_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"pid": 0, "updatedAt": time.time(), "accounts": [snapshot().to_wire()]}),
        encoding="utf-8",
    )


class TestFormatSnapshot:
    def test_explains_that_the_gateway_must_be_up(self) -> None:
        output = format_snapshot(None)
        assert "No KakaoTalk account is running" in output
        assert "hermes status" in output

    def test_shows_the_code_and_the_pair_instruction(self) -> None:
        output = format_snapshot(snapshot(expires_in_seconds=185))
        assert "CODE-1234" in output
        assert "/pair CODE-1234" in output
        assert "3분 5초" in output

    def test_hides_the_code_once_paired(self) -> None:
        output = format_snapshot(
            snapshot(state="paired", pairing_code=None, paired_user_id="user-1")
        )
        assert "CODE-1234" not in output
        assert "user-1" in output

    def test_paired_state_spells_out_the_unpair_step(self) -> None:
        # `pairing new` only drops the gateway-side session. The relay rejects a
        # second /pair while the conversation is still paired, and nothing in
        # the plugin can clear that — only /unpair in KakaoTalk can.
        output = format_snapshot(snapshot(state="paired", pairing_code=None))
        assert "/unpair" in output
        assert output.index("/unpair") < output.index("/pair <code>")

    def test_handles_a_paired_account_with_no_user(self) -> None:
        # Happens when a saved session token was restored rather than paired.
        output = format_snapshot(snapshot(state="paired", pairing_code=None, paired_user_id=None))
        assert "state: paired" in output
        assert "(None)" not in output

    @pytest.mark.parametrize("state", ["expired", "unpaired"])
    def test_points_at_pairing_new(self, state: str) -> None:
        output = format_snapshot(snapshot(state=state, pairing_code=None))
        assert "hermes kakao pairing new" in output

    def test_surfaces_why_reissue_is_unavailable(self) -> None:
        output = format_snapshot(
            snapshot(can_reissue=False, reissue_blocked_reason="uses a configured relay token")
        )
        assert "uses a configured relay token" in output


class TestStaleWarning:
    # The OpenClaw version claimed the writer was dead whenever state looked
    # stale, including when only age had been checked. That false detail cost a
    # real investigation, so each reason must render its own wording.
    def test_writer_gone_says_so(self) -> None:
        state = PairingStateFile(pid=0, updated_at=time.time(), accounts=[])
        message = stale_warning(state, describe_staleness(state))
        assert "no longer running" in message

    def test_too_old_does_not_claim_the_process_died(self) -> None:
        state = PairingStateFile(
            pid=os.getpid(), updated_at=time.time() - 20 * 60, accounts=[]
        )
        message = stale_warning(state, describe_staleness(state))
        assert "still appears to be running" in message
        assert "no longer running" not in message


class TestRegistration:
    def test_registers_the_kakao_command(self) -> None:
        captured: dict[str, Any] = {}

        class Ctx:
            def register_cli_command(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        register_pairing_cli(Ctx())

        assert captured["name"] == CLI_COMMAND_NAME
        assert callable(captured["setup_fn"])
        assert callable(captured["handler_fn"])

    def test_parser_builds_the_subcommands(self) -> None:
        parser = argparse.ArgumentParser(prog="kakao")
        setup_parser(parser)

        parsed = parser.parse_args(["pairing", "status", "--json"])
        assert parsed.kakao_action == "status"
        assert parsed.json is True

        parsed = parser.parse_args(["pairing", "new", "--timeout", "45"])
        assert parsed.kakao_action == "new"
        assert parsed.timeout == 45.0


class TestStatus:
    def test_reads_the_published_state(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pairing_state([snapshot()])

        assert handle_command(args()) == 0
        assert "CODE-1234" in capsys.readouterr().out

    def test_selects_the_requested_account(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pairing_state(
            [
                snapshot(account_id="a", pairing_code="CODE-A"),
                snapshot(account_id="b", pairing_code="CODE-B"),
            ]
        )

        handle_command(args(account="b"))
        assert "CODE-B" in capsys.readouterr().out

    def test_json_is_parseable(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # The OpenClaw port shipped a logger prefix that made --json unparseable;
        # output here goes straight to stdout for exactly that reason.
        write_pairing_state([snapshot()])

        handle_command(args(json=True))

        payload = json.loads(capsys.readouterr().out)
        assert payload["account"]["pairingCode"] == "CODE-1234"
        assert payload["stale"] is False

    def test_is_non_destructive(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pairing_state([snapshot()])

        for _ in range(3):
            handle_command(args())

        # Each render prints the code twice (the code line and the /pair line),
        # so count the instruction line rather than the bare code.
        assert capsys.readouterr().out.count("/pair CODE-1234") == 3

    def test_explains_when_nothing_is_publishing(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert handle_command(args()) == 1
        assert "No KakaoTalk pairing state found" in capsys.readouterr().out

    def test_warns_about_stale_state_but_still_shows_it(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Staleness detection has been wrong before, so it must not be able to
        # withhold what is actually on disk.
        write_stale_state()

        assert handle_command(args()) == 0
        output = capsys.readouterr().out
        assert "may be out of date" in output
        assert "CODE-1234" in output

    def test_marks_staleness_in_json(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_stale_state()

        handle_command(args(json=True))

        payload = json.loads(capsys.readouterr().out)
        assert payload["stale"] is True
        assert payload["staleReason"] == "writer-gone"


class TestNew:
    def test_writes_a_request_the_gateway_can_consume(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pairing_state([snapshot(state="paired", pairing_code=None)])

        # Times out because no gateway is running to honour it.
        assert handle_command(args(kakao_action="new", timeout=0.2)) == 1

        request = json.loads((resolve_state_dir() / REQUEST_FILE).read_text(encoding="utf-8"))
        assert request["timeoutSeconds"] == 0.2
        assert isinstance(request["id"], str)
        assert "Timed out" in capsys.readouterr().out

    def test_ignores_a_code_that_predates_the_request(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # An old pending code must not be mistaken for a newly issued one.
        write_pairing_state([snapshot(pairing_code="CODE-OLD", issued_at=time.time() - 60)])

        assert handle_command(args(kakao_action="new", timeout=0.2)) == 1
        assert "Timed out" in capsys.readouterr().out

    def test_rejects_a_non_positive_timeout(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_pairing_state([snapshot()])

        assert handle_command(args(kakao_action="new", timeout=0)) == 1
        assert "--timeout must be a positive number" in capsys.readouterr().out

    def test_fails_fast_when_nothing_is_publishing(
        self, isolated_state_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert handle_command(args(kakao_action="new")) == 1
        assert "No KakaoTalk pairing state found" in capsys.readouterr().out
        # No request should be left for a gateway that is not there.
        assert not (resolve_state_dir() / REQUEST_FILE).exists()


class TestDispatch:
    def test_unknown_action_prints_usage(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert handle_command(args(kakao_action=None)) == 2
        assert "usage:" in capsys.readouterr().out

    def test_pairing_errors_become_exit_code_one(self) -> None:
        # PairingCliError is the operator-facing failure type; it must never
        # escape as a traceback.
        assert issubclass(PairingCliError, Exception)
