"""Wire types for the relay transport.

Ported from the relay half of ``src/types.ts``. The relay's wire format is not
documented anywhere upstream — these shapes were recovered from the OpenClaw
client implementation. See docs/relay-wire-protocol.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SSEEventType = Literal["message", "ping", "error", "pairing_complete", "pairing_expired"]
SessionStatus = Literal["pending_pairing", "paired", "expired", "disconnected"]


@dataclass(frozen=True)
class NormalizedMessage:
    user_id: str
    text: str
    channel_id: str


@dataclass(frozen=True)
class InboundMessage:
    id: str
    conversation_key: str
    normalized: NormalizedMessage
    created_at: str  # ISO 8601
    kakao_payload: dict[str, Any] | None = None

    @classmethod
    def from_wire(cls, data: dict[str, Any]) -> InboundMessage:
        normalized = data.get("normalized") or {}
        return cls(
            id=str(data.get("id", "")),
            conversation_key=str(data.get("conversationKey", "")),
            normalized=NormalizedMessage(
                user_id=str(normalized.get("userId", "")),
                text=str(normalized.get("text", "")),
                channel_id=str(normalized.get("channelId", "")),
            ),
            created_at=str(data.get("createdAt", "")),
            kakao_payload=data.get("kakaoPayload"),
        )


@dataclass(frozen=True)
class SSEEvent:
    event: SSEEventType
    data: Any
    id: str | None = None


@dataclass(frozen=True)
class ParsedChunk:
    events: list[SSEEvent] = field(default_factory=list)
    consumed: int = 0
    parse_errors: int = 0


@dataclass(frozen=True)
class CreateSessionResponse:
    session_token: str
    pairing_code: str
    expires_in: int
    status: SessionStatus


@dataclass(frozen=True)
class SessionStatusResponse:
    status: SessionStatus
    paired_at: str | None = None
    kakao_user_id: str | None = None


@dataclass(frozen=True)
class RelayError:
    code: str
    message: str


@dataclass(frozen=True)
class SendReplyResponse:
    success: bool
    delivered_at: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    latency_ms: int | None = None
    error: str | None = None
