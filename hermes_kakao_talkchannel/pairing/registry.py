"""Pairing state registry.

Owns the answer to "what is the current pairing code?" so an operator can ask
for it over the ``hermes`` CLI instead of restarting the gateway and grepping
logs inside a five-minute window.

Ported from the OpenClaw plugin's ``src/pairing/registry.ts`` after that design
was verified end to end on a live gateway (2026-07-20). Three properties this
module exists to guarantee:

1. Reads are **non-destructive**. The original accessor deleted the entry on
   read, so a code could only ever be retrieved once.
2. State is **cleared** when pairing completes, expires, or the account stops,
   so a dead code cannot linger in memory.
3. ``pairing_complete`` is **deduplicated**. The relay delivers it roughly four
   times in two seconds, and each one used to trigger a config write.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

logger = logging.getLogger(__name__)

PairingState = Literal["unpaired", "pending", "paired", "expired"]

#: Window within which repeated ``pairing_complete`` events for the same user
#: are treated as duplicates. The relay emits ~4 in 2s.
PAIRING_COMPLETE_DEDUPE_SECONDS = 10.0


@dataclass(frozen=True)
class PairingSnapshot:
    account_id: str
    channel_id: str
    state: PairingState
    #: Present only while ``state == "pending"``.
    pairing_code: str | None
    #: Epoch seconds. Present only while ``state == "pending"``.
    expires_at: float | None
    #: Live countdown; negative values are clamped to 0.
    expires_in_seconds: int | None
    issued_at: float | None
    paired_user_id: str | None
    paired_at: float | None
    #: False when the account uses a static token (nothing to re-issue).
    can_reissue: bool
    reissue_blocked_reason: str | None

    def to_wire(self) -> dict[str, object]:
        """Serializable form, used for the state file and ``--json`` output."""
        return {
            "accountId": self.account_id,
            "channelId": self.channel_id,
            "state": self.state,
            "pairingCode": self.pairing_code,
            "expiresAt": self.expires_at,
            "expiresInSeconds": self.expires_in_seconds,
            "issuedAt": self.issued_at,
            "pairedUserId": self.paired_user_id,
            "pairedAt": self.paired_at,
            "canReissue": self.can_reissue,
            "reissueBlockedReason": self.reissue_blocked_reason,
        }

    @classmethod
    def from_wire(cls, data: dict[str, object]) -> PairingSnapshot:
        return cls(
            account_id=str(data.get("accountId", "")),
            channel_id=str(data.get("channelId", "")),
            state=data.get("state", "unpaired"),  # type: ignore[arg-type]
            pairing_code=data.get("pairingCode"),  # type: ignore[arg-type]
            expires_at=data.get("expiresAt"),  # type: ignore[arg-type]
            expires_in_seconds=data.get("expiresInSeconds"),  # type: ignore[arg-type]
            issued_at=data.get("issuedAt"),  # type: ignore[arg-type]
            paired_user_id=data.get("pairedUserId"),  # type: ignore[arg-type]
            paired_at=data.get("pairedAt"),  # type: ignore[arg-type]
            can_reissue=bool(data.get("canReissue", False)),
            reissue_blocked_reason=data.get("reissueBlockedReason"),  # type: ignore[arg-type]
        )


class AccountController(Protocol):
    """What the adapter must provide for an account to support re-issue."""

    async def request_new_pairing(self, timeout_seconds: float) -> PairingSnapshot:
        """Drop the current session and obtain a fresh code, without restarting."""
        ...

    def reissue_blocked_reason(self) -> str | None:
        """Why re-issue is unavailable, or None when it is available."""
        ...


@dataclass
class _AccountEntry:
    account_id: str
    channel_id: str
    state: PairingState = "unpaired"
    pairing_code: str | None = None
    expires_at: float | None = None
    issued_at: float | None = None
    paired_user_id: str | None = None
    paired_at: float | None = None
    controller: AccountController | None = None
    #: Futures waiting for the next ``record_pairing_required``.
    waiters: list[Callable[[PairingSnapshot], None]] = field(default_factory=list)


_accounts: dict[str, _AccountEntry] = {}

#: Change listeners. The gateway uses these to publish state to disk, since the
#: CLI runs in a separate process and Hermes has no CLI-to-gateway channel.
ChangeListener = Callable[[], None]
_change_listeners: set[ChangeListener] = set()


def on_pairing_change(listener: ChangeListener) -> Callable[[], None]:
    _change_listeners.add(listener)

    def unsubscribe() -> None:
        _change_listeners.discard(listener)

    return unsubscribe


def _notify_change() -> None:
    for listener in list(_change_listeners):
        try:
            listener()
        except Exception:  # noqa: BLE001
            # A failing publisher must never break the pairing flow.
            logger.debug("Pairing change listener failed", exc_info=True)


def _entry_for(account_id: str, channel_id: str | None = None) -> _AccountEntry:
    entry = _accounts.get(account_id)
    if entry is None:
        entry = _AccountEntry(account_id=account_id, channel_id=channel_id or account_id)
        _accounts[account_id] = entry
    if channel_id:
        entry.channel_id = channel_id
    return entry


def _to_snapshot(entry: _AccountEntry, now: float | None = None) -> PairingSnapshot:
    now = time.time() if now is None else now

    # A pending code that has run out reads as expired even if the relay has not
    # said so yet — an operator must never be handed a dead code.
    expired = entry.state == "pending" and entry.expires_at is not None and now >= entry.expires_at
    state: PairingState = "expired" if expired else entry.state
    pending = state == "pending"

    # Not `or`: a controller returning None means re-issue IS available, which
    # is exactly the falsy value a short-circuit would swallow.
    if entry.controller is not None:
        blocked = entry.controller.reissue_blocked_reason()
    else:
        blocked = "account is not running"

    return PairingSnapshot(
        account_id=entry.account_id,
        channel_id=entry.channel_id,
        state=state,
        pairing_code=entry.pairing_code if pending else None,
        expires_at=entry.expires_at if pending else None,
        expires_in_seconds=(
            max(0, round(entry.expires_at - now)) if pending and entry.expires_at else None
        ),
        issued_at=entry.issued_at,
        paired_user_id=entry.paired_user_id,
        paired_at=entry.paired_at,
        can_reissue=blocked is None,
        reissue_blocked_reason=blocked,
    )


# -- lifecycle wiring (called from the adapter) -----------------------------


def register_account(account_id: str, channel_id: str, controller: AccountController) -> None:
    entry = _entry_for(account_id, channel_id)
    entry.controller = controller
    _notify_change()


def unregister_account(account_id: str) -> None:
    entry = _accounts.pop(account_id, None)
    if entry is None:
        return
    # Waiters must not hang forever once the account is gone.
    snapshot = _to_snapshot(entry)
    for resolve in entry.waiters:
        resolve(snapshot)
    entry.waiters.clear()
    _notify_change()


def record_pairing_required(
    account_id: str,
    channel_id: str,
    pairing_code: str,
    expires_in_seconds: int,
) -> PairingSnapshot:
    entry = _entry_for(account_id, channel_id)
    now = time.time()

    entry.state = "pending"
    entry.pairing_code = pairing_code
    entry.issued_at = now
    entry.expires_at = now + expires_in_seconds
    entry.paired_user_id = None
    entry.paired_at = None

    snapshot = _to_snapshot(entry, now)
    _notify_change()
    for resolve in entry.waiters:
        resolve(snapshot)
    entry.waiters.clear()
    return snapshot


def record_pairing_complete(account_id: str, channel_id: str, kakao_user_id: str) -> bool:
    """Record a completed pairing.

    Returns True for the first completion and False for the duplicates the relay
    sends immediately afterwards. Callers must skip side effects on False.
    """
    entry = _entry_for(account_id, channel_id)
    now = time.time()

    is_duplicate = (
        entry.state == "paired"
        and entry.paired_user_id == kakao_user_id
        and entry.paired_at is not None
        and now - entry.paired_at < PAIRING_COMPLETE_DEDUPE_SECONDS
    )
    if is_duplicate:
        return False

    entry.state = "paired"
    entry.pairing_code = None
    entry.expires_at = None
    entry.paired_user_id = kakao_user_id
    entry.paired_at = now
    _notify_change()
    return True


def record_pairing_expired(account_id: str, channel_id: str) -> None:
    entry = _entry_for(account_id, channel_id)
    entry.state = "expired"
    entry.pairing_code = None
    entry.expires_at = None
    _notify_change()


def record_session_reused(account_id: str, channel_id: str) -> None:
    """Mark an account paired because a saved session token was restored."""
    entry = _entry_for(account_id, channel_id)
    if entry.state == "pending":
        return
    entry.state = "paired"
    entry.pairing_code = None
    entry.expires_at = None
    _notify_change()


def record_session_invalidated(account_id: str, channel_id: str) -> None:
    """Forget paired state — the relay rejected the token."""
    entry = _entry_for(account_id, channel_id)
    entry.state = "unpaired"
    entry.pairing_code = None
    entry.expires_at = None
    entry.paired_user_id = None
    entry.paired_at = None
    _notify_change()


# -- reads ------------------------------------------------------------------


def get_pairing_snapshot(account_id: str | None = None) -> PairingSnapshot | None:
    if account_id:
        entry = _accounts.get(account_id)
        return _to_snapshot(entry) if entry else None
    for entry in _accounts.values():
        return _to_snapshot(entry)
    return None


def list_pairing_snapshots() -> list[PairingSnapshot]:
    return [_to_snapshot(entry) for entry in _accounts.values()]


def add_pairing_waiter(
    account_id: str, resolve: Callable[[PairingSnapshot], None]
) -> Callable[[], None]:
    """Register a callback for the next code issued for this account."""
    entry = _entry_for(account_id)
    entry.waiters.append(resolve)

    def cancel() -> None:
        if resolve in entry.waiters:
            entry.waiters.remove(resolve)

    return cancel


async def request_new_pairing(
    account_id: str | None,
    timeout_seconds: float,
) -> PairingSnapshot:
    entry = (
        _accounts.get(account_id) if account_id else next(iter(_accounts.values()), None)
    )

    if entry is None:
        raise RuntimeError(
            f'Unknown KakaoTalk account "{account_id}". Is the gateway running?'
            if account_id
            else "No KakaoTalk account is running. Start the gateway first."
        )
    if entry.controller is None:
        raise RuntimeError(f'KakaoTalk account "{entry.account_id}" is not running.')

    blocked = entry.controller.reissue_blocked_reason()
    if blocked:
        raise RuntimeError(blocked)

    return await entry.controller.request_new_pairing(timeout_seconds)


def reset_pairing_registry() -> None:
    """Test seam."""
    _accounts.clear()
    _change_listeners.clear()


__all__ = [
    "PAIRING_COMPLETE_DEDUPE_SECONDS",
    "AccountController",
    "Awaitable",
    "PairingSnapshot",
    "PairingState",
    "add_pairing_waiter",
    "get_pairing_snapshot",
    "list_pairing_snapshots",
    "on_pairing_change",
    "record_pairing_complete",
    "record_pairing_expired",
    "record_pairing_required",
    "record_session_invalidated",
    "record_session_reused",
    "register_account",
    "request_new_pairing",
    "reset_pairing_registry",
    "unregister_account",
]
