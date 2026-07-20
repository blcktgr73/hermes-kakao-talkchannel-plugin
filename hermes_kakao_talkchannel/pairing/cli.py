"""``hermes kakao pairing …`` CLI commands.

The operator-facing answer to "how do I get the pairing code over SSH?".

## Why this talks to files

Hermes has no CLI-to-gateway channel — ``gateway/drain_control.py`` states that
outright. The gateway publishes pairing state to ``pairing-state.json`` and
consumes re-issue requests from ``pairing-request.json``; this module is the
other end. The equivalent OpenClaw design was verified end to end on a live
gateway before being ported here.

Everything is synchronous on purpose: ``register_cli_command`` hands the handler
only an argparse namespace, with no guarantee about a running event loop.

Output goes to ``print`` rather than a logger. In the OpenClaw port the logger
prefixed every line with a timestamp, which silently made ``--json`` unparseable.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from .registry import PairingSnapshot
from .state_file import (
    PairingStateFile,
    Staleness,
    describe_staleness,
    read_pairing_state,
    write_pairing_request,
)

CLI_COMMAND_NAME = "kakao"

DEFAULT_REISSUE_TIMEOUT_SECONDS = 30.0
#: How often the CLI re-reads the state file while waiting for a new code.
POLL_INTERVAL_SECONDS = 0.5
#: Extra wait on top of ``--timeout``, covering the gateway's own poll interval.
REISSUE_POLL_GRACE_SECONDS = 2.0


class PairingCliError(Exception):
    """Operator-facing failure. The message is the whole user experience."""


def _not_publishing() -> PairingCliError:
    return PairingCliError(
        "No KakaoTalk pairing state found. The gateway publishes it only while a "
        "KakaoTalk account is running.\n"
        "  Check:  hermes status\n"
        "          hermes gateway status"
    )


def stale_warning(state: PairingStateFile, staleness: Staleness) -> str:
    """Describe staleness using only what was actually checked.

    The OpenClaw version asserted the writing process was dead whenever state
    looked stale, including when staleness had been decided on age alone and the
    pid never examined. That claim was false on a live VM and cost an
    investigation, so the reason is reported explicitly here.
    """
    age = round(staleness.age_seconds)
    if staleness.reason == "writer-gone":
        detail = f"pid {state.pid} wrote it and that process is no longer running"
    else:
        detail = (
            f"pid {state.pid} still appears to be running but has not "
            f"refreshed it in {age}s"
        )
    return f"warning: this pairing state may be out of date — {detail}.\n  Check: hermes status"


def _read_state() -> tuple[PairingStateFile, Staleness]:
    """Read published state. Staleness is reported, never enforced.

    An earlier OpenClaw version refused to proceed on stale state; the detection
    then misfired on a healthy gateway and blocked a legitimate operation.
    Showing what we have, clearly flagged, beats refusing.
    """
    state = read_pairing_state()
    if state is None:
        raise _not_publishing()
    return state, describe_staleness(state)


def _select_account(
    state: PairingStateFile, account_id: str | None
) -> PairingSnapshot | None:
    if account_id:
        return next((a for a in state.accounts if a.account_id == account_id), None)
    return state.accounts[0] if state.accounts else None


def format_snapshot(snapshot: PairingSnapshot | None) -> str:
    if snapshot is None:
        return (
            "No KakaoTalk account is running.\n\n"
            "The gateway must be up before a pairing code exists. Check:\n"
            "  hermes status"
        )

    lines = [f"account: {snapshot.account_id} ({snapshot.channel_id})"]

    if snapshot.state == "pending":
        remaining = snapshot.expires_in_seconds or 0
        lines += [
            "",
            f"  페어링 코드: {snapshot.pairing_code}",
            f"  카카오톡에서 입력: /pair {snapshot.pairing_code}",
            f"  남은 시간: {remaining // 60}분 {remaining % 60}초",
        ]
    elif snapshot.state == "paired":
        suffix = f" ({snapshot.paired_user_id})" if snapshot.paired_user_id else ""
        lines.append(f"  state: paired{suffix}")
        lines.append("  A new code is not needed. Use `pairing new` to force one.")
    elif snapshot.state == "expired":
        lines.append("  state: expired — the last code is no longer valid.")
        lines.append("  Run: hermes kakao pairing new")
    else:
        lines.append("  state: unpaired — no code has been issued yet.")
        lines.append("  Run: hermes kakao pairing new")

    if not snapshot.can_reissue and snapshot.reissue_blocked_reason:
        lines += ["", f"  note: {snapshot.reissue_blocked_reason}"]

    return "\n".join(lines)


def _await_new_code(
    account_id: str | None, requested_at: float, timeout_seconds: float
) -> PairingSnapshot:
    """Wait for the gateway to publish a code issued after ``requested_at``.

    Comparing against ``issued_at`` is what distinguishes a genuinely new code
    from one that was already sitting there.
    """
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        time.sleep(POLL_INTERVAL_SECONDS)

        state = read_pairing_state()
        snapshot = _select_account(state, account_id) if state else None
        if (
            snapshot is not None
            and snapshot.state == "pending"
            and snapshot.issued_at is not None
            and snapshot.issued_at >= requested_at
        ):
            return snapshot

    raise PairingCliError(
        f"Timed out after {round(timeout_seconds)}s waiting for a new pairing code.\n"
        "  The gateway may not have picked up the request. Check:\n"
        "    hermes status\n"
        "    journalctl --user -u hermes-gateway --since '2 min ago' | grep -i kakao"
    )


# -- handlers ---------------------------------------------------------------


def _handle_status(args: argparse.Namespace) -> int:
    state, staleness = _read_state()
    snapshot = _select_account(state, getattr(args, "account", None))

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "accounts": [a.to_wire() for a in state.accounts],
                    "account": snapshot.to_wire() if snapshot else None,
                    "stale": staleness.stale,
                    "staleReason": staleness.reason,
                },
                indent=2,
            )
        )
        return 0

    if staleness.stale:
        print(stale_warning(state, staleness))
    print(format_snapshot(snapshot))
    return 0


def _handle_new(args: argparse.Namespace) -> int:
    # Only a missing file is fatal — there is then nothing to ask. A stale file
    # is reported and the request still goes out: if the gateway is in fact
    # alive it picks it up, and if not, the wait below says so.
    state, staleness = _read_state()
    as_json = getattr(args, "json", False)
    if staleness.stale and not as_json:
        print(stale_warning(state, staleness))

    timeout_seconds = float(getattr(args, "timeout", DEFAULT_REISSUE_TIMEOUT_SECONDS))
    if timeout_seconds <= 0:
        raise PairingCliError(
            f"--timeout must be a positive number of seconds (got {timeout_seconds})"
        )

    account_id = getattr(args, "account", None)
    request = write_pairing_request(account_id, timeout_seconds)
    snapshot = _await_new_code(
        account_id, request.requested_at, timeout_seconds + REISSUE_POLL_GRACE_SECONDS
    )

    if as_json:
        print(json.dumps({"account": snapshot.to_wire()}, indent=2))
        return 0

    print(format_snapshot(snapshot))
    return 0


def handle_command(args: argparse.Namespace) -> int:
    """Single entry point; ``register_cli_command`` binds one handler."""
    action = getattr(args, "kakao_action", None)

    try:
        if action == "status":
            return _handle_status(args)
        if action == "new":
            return _handle_new(args)
    except PairingCliError as error:
        print(str(error))
        return 1

    print("usage: hermes kakao pairing {status,new}")
    return 2


def setup_parser(parser: argparse.ArgumentParser) -> None:
    """Build ``kakao pairing {status,new}``."""
    groups = parser.add_subparsers(dest="kakao_group")
    pairing = groups.add_parser("pairing", help="Inspect or re-issue the pairing code")
    actions = pairing.add_subparsers(dest="kakao_action")

    status = actions.add_parser(
        "status", help="Show the current pairing code without restarting the gateway"
    )
    status.add_argument("--account", help="Account id (defaults to the only running account)")
    status.add_argument("--json", action="store_true", help="Emit raw JSON")

    new = actions.add_parser("new", help="Drop the current session and issue a fresh code")
    new.add_argument("--account", help="Account id (defaults to the only running account)")
    new.add_argument("--json", action="store_true", help="Emit raw JSON")
    new.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_REISSUE_TIMEOUT_SECONDS,
        help="How long to wait for the relay (seconds)",
    )


def register_pairing_cli(ctx: Any) -> None:
    ctx.register_cli_command(
        name=CLI_COMMAND_NAME,
        help="KakaoTalk TalkChannel operations",
        setup_fn=setup_parser,
        handler_fn=handle_command,
        description="Inspect or re-issue the KakaoTalk pairing code.",
    )
