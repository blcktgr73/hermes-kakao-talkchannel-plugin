"""Relay HTTP client: outbound replies and health checks.

Faithful port of ``src/relay/client.ts``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import aiohttp

from .models import HealthResult, SendReplyResponse

DEFAULT_TIMEOUT_MS = 10000
AUTH_ERROR_STATUSES = frozenset({401, 410})


@dataclass
class RelayClientConfig:
    relay_url: str
    relay_token: str
    timeout_ms: int | None = None


class RelayHttpError(Exception):
    """Non-2xx response from the relay."""

    def __init__(self, status: int, status_text: str, detail: str) -> None:
        super().__init__(f"HTTP {status} {status_text}: {detail}")
        self.status = status
        self.status_text = status_text
        self.is_auth_error = status in AUTH_ERROR_STATUSES


def parse_error_body(body: Any) -> str:
    """Extract a human-readable message from a relay error body.

    Resolution order matches the original; first match wins.
    """
    if body is None:
        return "Unknown error"
    if not isinstance(body, dict):
        return str(body)
    error = body.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(body.get("message"), str):
        return body["message"]
    return "Unknown error"


def _normalize_base_url(relay_url: str) -> str:
    return relay_url if relay_url.endswith("/") else relay_url + "/"


async def send_reply(
    config: RelayClientConfig,
    message_id: str,
    response: dict[str, Any],
) -> SendReplyResponse:
    """Push a KakaoTalk skill response back through the relay."""
    if not message_id or not isinstance(message_id, str):
        raise ValueError("send_reply: message_id is required and must be a non-empty string")
    if not config.relay_url or not isinstance(config.relay_url, str):
        raise ValueError("send_reply: relay_url is required and must be a non-empty string")
    if not config.relay_token or not isinstance(config.relay_token, str):
        raise ValueError("send_reply: relay_token is required and must be a non-empty string")

    url = f"{_normalize_base_url(config.relay_url)}openclaw/reply"
    timeout = aiohttp.ClientTimeout(total=(config.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000)

    async with aiohttp.ClientSession(timeout=timeout) as session, session.post(
        url,
        json={"messageId": message_id, "response": response},
        headers={
            "Authorization": f"Bearer {config.relay_token}",
            "Content-Type": "application/json",
        },
    ) as http_response:
        if http_response.status < 200 or http_response.status >= 300:
            try:
                error_body = await http_response.json()
            except Exception:  # noqa: BLE001
                error_body = {}
            raise RelayHttpError(
                http_response.status,
                http_response.reason or "",
                parse_error_body(error_body),
            )

        data = await http_response.json()
        return _validate_send_reply_response(data)


def _validate_send_reply_response(data: Any) -> SendReplyResponse:
    if not isinstance(data, dict):
        raise ValueError("Invalid relay response: expected object")
    if not isinstance(data.get("success"), bool):
        raise ValueError("Invalid relay response: success must be a boolean")
    return SendReplyResponse(
        success=data["success"],
        delivered_at=data.get("deliveredAt"),
        error=data.get("error"),
    )


async def health_check(config: RelayClientConfig) -> HealthResult:
    """Probe relay reachability. Never raises.

    Normalized like every other relay call. The original concatenated
    ``/health`` onto a URL that already ends in a slash, producing
    ``https://host//health``. The relay registers the route as ``r.Get("/health")``
    at the root, and the fixed path returned ``ok`` with 85ms latency on a live
    gateway, so the extra slash was never intentional.
    """
    url = f"{_normalize_base_url(config.relay_url)}health"
    timeout = aiohttp.ClientTimeout(total=(config.timeout_ms or DEFAULT_TIMEOUT_MS) / 1000)
    started = time.monotonic()

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
            url, headers={"Authorization": f"Bearer {config.relay_token}"}
        ) as response:
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.status < 200 or response.status >= 300:
                return HealthResult(
                    ok=False,
                    latency_ms=latency_ms,
                    error=f"HTTP {response.status} {response.reason or ''}".strip(),
                )
            return HealthResult(ok=True, latency_ms=latency_ms)
    except Exception as error:  # noqa: BLE001
        latency_ms = int((time.monotonic() - started) * 1000)
        return HealthResult(
            ok=False, latency_ms=latency_ms, error=str(error) or "Unknown error"
        )
