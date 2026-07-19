from __future__ import annotations

import json
from pathlib import Path

from hermes_kakao_talkchannel.transport.session_store import (
    forget_session_token,
    load_session_token,
    persist_session_token,
)


def test_load_returns_none_when_no_state_file_exists(isolated_state_dir: Path) -> None:
    assert load_session_token() is None


def test_persist_then_load_round_trips(isolated_state_dir: Path) -> None:
    persist_session_token("tok-abc")
    assert load_session_token() == "tok-abc"


def test_persist_writes_expected_json_layout(isolated_state_dir: Path) -> None:
    persist_session_token("tok-abc", "channel-1")
    store = isolated_state_dir / "kakao-talkchannel" / "session.json"
    assert json.loads(store.read_text(encoding="utf-8")) == {
        "channel-1": {"sessionToken": "tok-abc"}
    }


def test_channels_are_stored_independently(isolated_state_dir: Path) -> None:
    persist_session_token("tok-a", "a")
    persist_session_token("tok-b", "b")
    assert load_session_token("a") == "tok-a"
    assert load_session_token("b") == "tok-b"


def test_forget_removes_only_the_named_channel(isolated_state_dir: Path) -> None:
    persist_session_token("tok-a", "a")
    persist_session_token("tok-b", "b")
    forget_session_token("a")
    assert load_session_token("a") is None
    assert load_session_token("b") == "tok-b"


def test_forget_is_a_no_op_when_nothing_is_stored(isolated_state_dir: Path) -> None:
    forget_session_token()  # must not raise


def test_corrupt_state_file_does_not_raise(isolated_state_dir: Path) -> None:
    store = isolated_state_dir / "kakao-talkchannel" / "session.json"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text("{ not json", encoding="utf-8")

    assert load_session_token() is None
    persist_session_token("tok-new")  # overwrites the corrupt file
    assert load_session_token() == "tok-new"
