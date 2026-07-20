"""Pairing state, its on-disk hand-off to the CLI, and the CLI itself.

Ported from the OpenClaw plugin after that design was verified on a live
gateway (2026-07-20). The shape is dictated by a constraint both hosts share:
the CLI runs in a different process from the gateway and cannot call into it.
"""

from __future__ import annotations

from .cli import CLI_COMMAND_NAME, format_snapshot, register_pairing_cli
from .publisher import PairingPublisher
from .registry import (
    AccountController,
    PairingSnapshot,
    PairingState,
    get_pairing_snapshot,
    list_pairing_snapshots,
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
from .state_file import (
    describe_staleness,
    read_pairing_state,
    resolve_state_dir,
    write_pairing_state,
)

__all__ = [
    "CLI_COMMAND_NAME",
    "AccountController",
    "PairingPublisher",
    "PairingSnapshot",
    "PairingState",
    "describe_staleness",
    "format_snapshot",
    "get_pairing_snapshot",
    "list_pairing_snapshots",
    "read_pairing_state",
    "record_pairing_complete",
    "record_pairing_expired",
    "record_pairing_required",
    "record_session_invalidated",
    "record_session_reused",
    "register_account",
    "register_pairing_cli",
    "request_new_pairing",
    "reset_pairing_registry",
    "resolve_state_dir",
    "unregister_account",
    "write_pairing_state",
]
