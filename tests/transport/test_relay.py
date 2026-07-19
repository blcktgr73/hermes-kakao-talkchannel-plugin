from __future__ import annotations

from typing import Any

import pytest

from hermes_kakao_talkchannel.config import KakaoConfig
from hermes_kakao_talkchannel.transport import relay as relay_module
from hermes_kakao_talkchannel.transport.models import CreateSessionResponse, RelayError
from hermes_kakao_talkchannel.transport.relay import (
    StreamCallbacks,
    resolve_token,
    sanitize_token_from_log,
)
from hermes_kakao_talkchannel.transport.session import RelayResult


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Authorization: Bearer abc123", "Authorization: ***"),
        ("sent Bearer abc123 to relay", "sent Bearer *** to relay"),
        ("?sessionToken=abc123&x=1", "?sessionToken=***&x=1"),
        ("?token=abc123", "?token=***"),
    ],
)
def test_sanitize_redacts_tokens(raw: str, expected: str) -> None:
    assert sanitize_token_from_log(raw) == expected


def test_sanitize_leaves_unrelated_text_alone() -> None:
    assert sanitize_token_from_log("connection refused") == "connection refused"


async def test_resolve_token_prefers_session_token() -> None:
    config = KakaoConfig(session_token="sess", relay_token="relay")
    resolved = await resolve_token(config, StreamCallbacks())
    assert resolved.token == "sess"
    assert resolved.is_new_session is False


async def test_resolve_token_falls_back_to_relay_token() -> None:
    resolved = await resolve_token(KakaoConfig(relay_token="relay"), StreamCallbacks())
    assert resolved.token == "relay"


async def test_resolve_token_reads_the_primary_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAKAO_RELAY_TOKEN", "from-env")
    resolved = await resolve_token(KakaoConfig(), StreamCallbacks())
    assert resolved.token == "from-env"


async def test_resolve_token_supports_the_legacy_openclaw_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENCLAW_TALKCHANNEL_RELAY_TOKEN", "legacy")
    resolved = await resolve_token(KakaoConfig(), StreamCallbacks())
    assert resolved.token == "legacy"


async def test_primary_env_var_wins_over_the_legacy_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAKAO_RELAY_TOKEN", "primary")
    monkeypatch.setenv("OPENCLAW_TALKCHANNEL_RELAY_TOKEN", "legacy")
    resolved = await resolve_token(KakaoConfig(), StreamCallbacks())
    assert resolved.token == "primary"


async def test_resolve_token_creates_a_session_and_reports_the_pairing_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_session(relay_url: str) -> RelayResult[CreateSessionResponse]:
        return RelayResult(
            ok=True,
            data=CreateSessionResponse(
                session_token="new-token",
                pairing_code="ABCD1234",
                expires_in=3600,
                status="pending_pairing",
            ),
        )

    monkeypatch.setattr(relay_module, "create_session", fake_create_session)

    seen: list[tuple[str, int]] = []
    callbacks = StreamCallbacks(on_pairing_required=lambda code, ttl: seen.append((code, ttl)))

    resolved = await resolve_token(KakaoConfig(), callbacks)

    assert resolved.token == "new-token"
    assert resolved.is_new_session is True
    assert seen == [("ABCD1234", 3600)]


async def test_resolve_token_raises_when_session_creation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_create_session(relay_url: str) -> RelayResult[Any]:
        return RelayResult(ok=False, error=RelayError(code="HTTP_500", message="relay down"))

    monkeypatch.setattr(relay_module, "create_session", failing_create_session)

    with pytest.raises(RuntimeError, match="Failed to create session: relay down"):
        await resolve_token(KakaoConfig(), StreamCallbacks())
