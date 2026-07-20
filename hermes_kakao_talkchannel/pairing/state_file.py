"""On-disk hand-off between the gateway process and the CLI process.

Hermes has **no CLI-to-gateway control channel at all**. The repository says so
outright in ``gateway/drain_control.py``: *"there is NO external control channel
into a running gateway"*. State moves between the two processes through files —
``gateway/pairing.py`` and the drain-control marker both work this way, and this
module follows them.

Two files, each single-writer:

- ``pairing-state.json``   — written by the gateway, read by the CLI.
- ``pairing-request.json`` — written by the CLI, consumed by the gateway.

Single-writer per file is deliberate. Atomic replace prevents torn reads but not
lost updates, so nothing here does read-modify-write across processes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .registry import PairingSnapshot

logger = logging.getLogger(__name__)

STATE_FILE = "pairing-state.json"
REQUEST_FILE = "pairing-request.json"

#: Age at which state is distrusted *even though* its writer still looks alive.
#:
#: This is a backstop, not the primary signal. The gateway heartbeats the file
#: (see ``publisher.py``), so a healthy file stays fresh no matter how long the
#: pairing itself goes unchanged. An earlier OpenClaw version checked age alone
#: against event-driven writes, which made every stable paired account look dead
#: after a minute — and then reported it as "the process is gone", which the
#: code had never checked.
STATE_STALE_AFTER_SECONDS = 10 * 60

StalenessReason = Literal["writer-gone", "too-old"]


@dataclass(frozen=True)
class PairingStateFile:
    #: Gateway process that wrote this, so the CLI can detect a dead writer.
    pid: int
    updated_at: float
    accounts: list[PairingSnapshot]


@dataclass(frozen=True)
class PairingRequestFile:
    id: str
    requested_at: float
    account_id: str | None
    timeout_seconds: float


@dataclass(frozen=True)
class Staleness:
    stale: bool
    #: None when not stale. Callers must report *this*, never a guess.
    reason: StalenessReason | None
    age_seconds: float


def _hermes_home() -> Path:
    """Where Hermes keeps its state, asking Hermes when it can be asked.

    Its own resolution is context-local override → ``HERMES_HOME`` →
    platform-native default, and profiles work by changing that home rather
    than by nesting under a shared one. Two things the fallback below gets
    wrong and the real function gets right: the per-task override used when one
    process serves several profiles, and the Windows default
    (``%LOCALAPPDATA%/hermes``, not ``~/.hermes``).
    """
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]

        return Path(get_hermes_home())
    except Exception:  # noqa: BLE001 - tests and non-Hermes environments
        base = os.environ.get("HERMES_HOME", "").strip()
        if base:
            return Path(base)
        if os.name == "nt":
            local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
            root = Path(local_appdata) if local_appdata else Path.home() / "AppData" / "Local"
            return root / "hermes"
        return Path.home() / ".hermes"


def resolve_state_dir() -> Path:
    return _hermes_home() / "kakao-talkchannel"


def _file_path(name: str) -> Path:
    return resolve_state_dir() / name


def _write_atomic(target: Path, data: Any) -> None:
    """Write atomically, then restrict permissions.

    Pairing codes are short-lived credentials, so the file is 0600. ``chmod`` is
    best effort — it is a no-op on Windows.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except BaseException:
        _remove_quietly(tmp_path)
        raise
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(target, 0o600)


def _read_json(target: Path) -> dict[str, Any] | None:
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        # Absent, unreadable, or mid-write garbage — all mean "nothing to act on".
        return None


def _remove_quietly(target: Path) -> None:
    """Delete without ever raising.

    These deletes run during account shutdown, where an exception would mask the
    real error. ``missing_ok`` covers absence; the suppress covers a locked or
    permission-denied file.
    """
    with contextlib.suppress(OSError):
        target.unlink(missing_ok=True)


# -- state: gateway writes, CLI reads ---------------------------------------


def write_pairing_state(accounts: list[PairingSnapshot]) -> None:
    _write_atomic(
        _file_path(STATE_FILE),
        {
            "pid": os.getpid(),
            "updatedAt": time.time(),
            "accounts": [account.to_wire() for account in accounts],
        },
    )


def read_pairing_state() -> PairingStateFile | None:
    data = _read_json(_file_path(STATE_FILE))
    if data is None:
        return None
    try:
        return PairingStateFile(
            pid=int(data["pid"]),
            updated_at=float(data["updatedAt"]),
            accounts=[PairingSnapshot.from_wire(item) for item in data.get("accounts", [])],
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_pairing_state() -> None:
    _remove_quietly(_file_path(STATE_FILE))


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # Signal 0 performs the existence/permission check without delivering.
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists but belongs to someone else.
        return True
    except OSError:
        return False
    return True


def describe_staleness(state: PairingStateFile, now: float | None = None) -> Staleness:
    """Why the state cannot be trusted to describe a live gateway, if it cannot.

    Returns the reason rather than a bare boolean because the OpenClaw version
    did not: it short-circuited on age but its caller's message claimed the
    writing process was dead. On a live VM that message sent us hunting a
    gateway crash that had never happened — the pid was alive and had simply
    never been checked. A diagnostic that asserts more than the code verified is
    worse than no diagnostic.
    """
    now = time.time() if now is None else now
    age = now - state.updated_at

    if not _is_process_alive(state.pid):
        return Staleness(stale=True, reason="writer-gone", age_seconds=age)
    if age > STATE_STALE_AFTER_SECONDS:
        return Staleness(stale=True, reason="too-old", age_seconds=age)
    return Staleness(stale=False, reason=None, age_seconds=age)


# -- request: CLI writes, gateway consumes ----------------------------------


def write_pairing_request(account_id: str | None, timeout_seconds: float) -> PairingRequestFile:
    request = PairingRequestFile(
        id=str(uuid.uuid4()),
        requested_at=time.time(),
        account_id=account_id,
        timeout_seconds=timeout_seconds,
    )
    _write_atomic(
        _file_path(REQUEST_FILE),
        {
            "id": request.id,
            "requestedAt": request.requested_at,
            "accountId": request.account_id,
            "timeoutSeconds": request.timeout_seconds,
        },
    )
    return request


def consume_pairing_request() -> PairingRequestFile | None:
    """Read and delete a pending request.

    Consuming on read keeps a request from being replayed. A request the gateway
    never saw — because it was not running — must not fire later out of context,
    which is why the publisher also clears the file on startup.
    """
    target = _file_path(REQUEST_FILE)
    data = _read_json(target)
    _remove_quietly(target)
    if data is None:
        return None
    try:
        return PairingRequestFile(
            id=str(data["id"]),
            requested_at=float(data["requestedAt"]),
            account_id=data.get("accountId"),
            timeout_seconds=float(data.get("timeoutSeconds", 30.0)),
        )
    except (KeyError, TypeError, ValueError):
        return None


def clear_pairing_request() -> None:
    _remove_quietly(_file_path(REQUEST_FILE))
