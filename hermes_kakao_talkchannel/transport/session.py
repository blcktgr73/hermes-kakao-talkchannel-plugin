"""Relay session creation and pairing status.

Faithful port of ``src/relay/session.ts``. Neither call sends an Authorization
header; ``create_session`` is how an unpaired client bootstraps a token, and the
returned pairing code is what the user sends to the KakaoTalk channel.

Both calls carry an explicit timeout. The original passed none, so an
unresponsive relay would stall pairing for aiohttp's 5-minute default.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar
from urllib.parse import quote

import aiohttp

from .models import CreateSessionResponse, RelayError, SessionStatusResponse

DEFAULT_RELAY_URL = "https://k.tess.dev/"

#: Matches the relay client's budget. Without it these calls inherit
#: aiohttp's 5-minute default and an unresponsive relay stalls pairing.
_TIMEOUT = aiohttp.ClientTimeout(total=10)

T = TypeVar("T")


@dataclass(frozen=True)
class RelayResult(Generic[T]):
    ok: bool
    data: T | None = None
    error: RelayError | None = None


def normalize_relay_url(url: str) -> str:
    return url if url.endswith("/") else url + "/"


async def create_session(relay_url: str = DEFAULT_RELAY_URL) -> RelayResult[CreateSessionResponse]:
    """Create an unpaired relay session and obtain a pairing code."""
    url = f"{normalize_relay_url(relay_url)}v1/sessions/create"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session, session.post(
            url, json={}, headers={"Content-Type": "application/json"}
        ) as response:
            if response.status < 200 or response.status >= 300:
                return RelayResult(
                    ok=False,
                    error=await _http_error(
                        response, f"Failed to create session: HTTP {response.status}"
                    ),
                )
            body: dict[str, Any] = await response.json()
            # AS-IS: the original performs no shape validation here.
            return RelayResult(
                ok=True,
                data=CreateSessionResponse(
                    session_token=body["sessionToken"],
                    pairing_code=body["pairingCode"],
                    expires_in=body["expiresIn"],
                    status=body["status"],
                ),
            )
    except Exception as error:  # noqa: BLE001
        return RelayResult(
            ok=False,
            error=RelayError(code="NETWORK_ERROR", message=str(error) or "Unknown error"),
        )


async def check_session_status(
    session_token: str,
    relay_url: str = DEFAULT_RELAY_URL,
) -> RelayResult[SessionStatusResponse]:
    """Poll a session's pairing status. The token travels in the path, not a header."""
    url = (
        f"{normalize_relay_url(relay_url)}v1/sessions/"
        f"{quote(session_token, safe='')}/status"
    )
    try:
        async with (
            aiohttp.ClientSession(timeout=_TIMEOUT) as session,
            session.get(url, headers={"Accept": "application/json"}) as response,
        ):
            if response.status < 200 or response.status >= 300:
                return RelayResult(
                    ok=False,
                    error=await _http_error(
                        response, f"Failed to check session: HTTP {response.status}"
                    ),
                )
            body: dict[str, Any] = await response.json()
            return RelayResult(
                ok=True,
                data=SessionStatusResponse(
                    status=body["status"],
                    paired_at=body.get("pairedAt"),
                    kakao_user_id=body.get("kakaoUserId"),
                ),
            )
    except Exception as error:  # noqa: BLE001
        return RelayResult(
            ok=False,
            error=RelayError(code="NETWORK_ERROR", message=str(error) or "Unknown error"),
        )


async def _http_error(response: aiohttp.ClientResponse, fallback: str) -> RelayError:
    """Build a RelayError from a failed response.

    AS-IS: only a top-level ``message`` key is read here — unlike
    ``client.parse_error_body``, which also understands ``error``.
    """
    try:
        body = await response.json()
    except Exception:  # noqa: BLE001
        body = {}
    message = body.get("message") if isinstance(body, dict) else None
    return RelayError(code=f"HTTP_{response.status}", message=message or fallback)
