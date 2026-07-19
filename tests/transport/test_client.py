"""Relay HTTP client tests against a real local aiohttp server.

Using a live server rather than a mocking library keeps the assertions honest
about URL construction, headers and status handling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp import web

from hermes_kakao_talkchannel.transport.client import (
    RelayClientConfig,
    RelayHttpError,
    health_check,
    parse_error_body,
    send_reply,
)


class RelayStub:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.reply_status = 200
        self.reply_body: Any = {"success": True, "deliveredAt": 1700000000}
        self.health_status = 200

    async def handle_reply(self, request: web.Request) -> web.Response:
        self.requests.append(
            {
                "path": request.path,
                "authorization": request.headers.get("Authorization"),
                "body": await request.json(),
            }
        )
        return web.json_response(self.reply_body, status=self.reply_status)

    async def handle_health(self, request: web.Request) -> web.Response:
        self.requests.append({"path": request.path})
        return web.json_response({"ok": True}, status=self.health_status)


@pytest.fixture()
async def relay() -> AsyncIterator[tuple[RelayStub, str]]:
    stub = RelayStub()
    app = web.Application()
    app.router.add_post("/openclaw/reply", stub.handle_reply)
    app.router.add_get("/health", stub.handle_health)
    # The double-slash URL that health_check actually produces (defect D1).
    app.router.add_get("//health", stub.handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()

    port = runner.addresses[0][1]
    try:
        yield stub, f"http://127.0.0.1:{port}/"
    finally:
        await runner.cleanup()


# -- parse_error_body ------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, "Unknown error"),
        ("boom", "boom"),
        (42, "42"),
        ({"error": "bad token"}, "bad token"),
        ({"error": {"message": "nested"}}, "nested"),
        ({"message": "top level"}, "top level"),
        ({}, "Unknown error"),
        ({"error": "wins", "message": "loses"}, "wins"),
    ],
)
def test_parse_error_body_resolution_order(body: Any, expected: str) -> None:
    assert parse_error_body(body) == expected


# -- send_reply ------------------------------------------------------------


@pytest.mark.parametrize(
    ("message_id", "token"),
    [("", "tok"), ("m1", "")],
)
async def test_send_reply_rejects_blank_arguments(message_id: str, token: str) -> None:
    with pytest.raises(ValueError):
        await send_reply(
            RelayClientConfig(relay_url="https://relay.example/", relay_token=token),
            message_id,
            {"version": "2.0"},
        )


async def test_send_reply_posts_expected_body_and_auth(
    relay: tuple[RelayStub, str],
) -> None:
    stub, base_url = relay
    response = {"version": "2.0", "template": {"outputs": []}}

    result = await send_reply(
        RelayClientConfig(relay_url=base_url, relay_token="tok-123"), "msg-1", response
    )

    assert result.success is True
    assert result.delivered_at == 1700000000
    assert stub.requests[0]["path"] == "/openclaw/reply"
    assert stub.requests[0]["authorization"] == "Bearer tok-123"
    assert stub.requests[0]["body"] == {"messageId": "msg-1", "response": response}


async def test_send_reply_normalizes_a_missing_trailing_slash(
    relay: tuple[RelayStub, str],
) -> None:
    stub, base_url = relay
    await send_reply(
        RelayClientConfig(relay_url=base_url.rstrip("/"), relay_token="tok"),
        "msg-1",
        {"version": "2.0"},
    )
    assert stub.requests[0]["path"] == "/openclaw/reply"


async def test_send_reply_raises_relay_http_error_on_failure(
    relay: tuple[RelayStub, str],
) -> None:
    stub, base_url = relay
    stub.reply_status = 500
    stub.reply_body = {"error": "relay exploded"}

    with pytest.raises(RelayHttpError) as excinfo:
        await send_reply(
            RelayClientConfig(relay_url=base_url, relay_token="tok"), "msg-1", {"version": "2.0"}
        )

    assert excinfo.value.status == 500
    assert excinfo.value.is_auth_error is False
    assert "relay exploded" in str(excinfo.value)


@pytest.mark.parametrize("status", [401, 410])
async def test_auth_statuses_are_flagged(relay: tuple[RelayStub, str], status: int) -> None:
    stub, base_url = relay
    stub.reply_status = status
    stub.reply_body = {"error": "nope"}

    with pytest.raises(RelayHttpError) as excinfo:
        await send_reply(
            RelayClientConfig(relay_url=base_url, relay_token="tok"), "msg-1", {"version": "2.0"}
        )

    assert excinfo.value.is_auth_error is True


async def test_send_reply_rejects_a_response_without_success(
    relay: tuple[RelayStub, str],
) -> None:
    stub, base_url = relay
    stub.reply_body = {"delivered": True}

    with pytest.raises(ValueError, match="success must be a boolean"):
        await send_reply(
            RelayClientConfig(relay_url=base_url, relay_token="tok"), "msg-1", {"version": "2.0"}
        )


# -- health_check ----------------------------------------------------------


async def test_health_check_ok(relay: tuple[RelayStub, str]) -> None:
    _, base_url = relay
    result = await health_check(RelayClientConfig(relay_url=base_url, relay_token="tok"))
    assert result.ok is True
    assert result.latency_ms is not None


async def test_health_check_produces_a_double_slash_url(relay: tuple[RelayStub, str]) -> None:
    # AS-IS (D1): health_check alone skips trailing-slash normalization.
    stub, base_url = relay
    assert base_url.endswith("/")
    await health_check(RelayClientConfig(relay_url=base_url, relay_token="tok"))
    assert stub.requests[0]["path"] == "//health"


async def test_health_check_reports_failure_without_raising(
    relay: tuple[RelayStub, str],
) -> None:
    stub, base_url = relay
    stub.health_status = 503
    result = await health_check(RelayClientConfig(relay_url=base_url, relay_token="tok"))
    assert result.ok is False
    assert result.error is not None
    assert "503" in result.error


async def test_health_check_swallows_connection_errors() -> None:
    result = await health_check(
        RelayClientConfig(relay_url="http://127.0.0.1:1/", relay_token="tok", timeout_ms=500)
    )
    assert result.ok is False
    assert result.error
