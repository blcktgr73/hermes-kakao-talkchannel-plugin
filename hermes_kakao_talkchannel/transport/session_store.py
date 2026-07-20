"""Persisting the relay session token across gateway restarts.

The OpenClaw plugin wrote this into ``openclaw.json`` via the host's
``runtime.config.mutateConfigFile``. Hermes exposes no equivalent — a plugin
cannot rewrite the host config file (docs/00-hermes-plugin-sdk.md §3) — so the
token lives in its own state file instead.

Semantic contract carried over from the original: only persist a token *after*
pairing completes. The relay deletes a session when its pairing code expires, so
persisting an unpaired token guarantees a 401 on next start.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_STORE_FILE = "session.json"


def _store_path() -> Path:
    # Shares the pairing state directory so both follow Hermes' own home
    # resolution — including the per-task profile override and the Windows
    # default, which an env-var-only lookup gets wrong.
    from ..pairing.state_file import resolve_state_dir

    return resolve_state_dir() / _STORE_FILE


def load_session_token(channel_id: str = "default") -> str | None:
    """Return the persisted session token, or None when absent or unreadable."""
    path = _store_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        token = data.get(channel_id, {}).get("sessionToken")
        return str(token) if token else None
    except Exception as error:  # noqa: BLE001
        logger.warning("[kakao-talkchannel:%s] Could not read saved pairing: %s", channel_id, error)
        return None


def persist_session_token(session_token: str, channel_id: str = "default") -> None:
    """Save a paired session token. Never raises."""
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, dict[str, str]] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                data = {}

        data.setdefault(channel_id, {})["sessionToken"] = session_token
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _restrict_permissions(path)

        logger.info(
            "[kakao-talkchannel:%s] Pairing saved; it will survive a gateway restart", channel_id
        )
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "[kakao-talkchannel:%s] Could not save the pairing: %s. "
            "Pairing will be required again after a restart.",
            channel_id,
            error,
        )


def forget_session_token(channel_id: str = "default") -> None:
    """Drop a persisted session token. Never raises."""
    path = _store_path()
    try:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        if channel_id in data:
            data[channel_id].pop("sessionToken", None)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            _restrict_permissions(path)
        logger.info("[kakao-talkchannel:%s] Saved pairing cleared", channel_id)
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "[kakao-talkchannel:%s] Could not clear the saved pairing: %s", channel_id, error
        )


def _restrict_permissions(path: Path) -> None:
    """Best-effort 0600, matching how Hermes stores pairing state. No-op on Windows."""
    with contextlib.suppress(OSError, NotImplementedError):
        os.chmod(path, 0o600)
