"""KakaoTalk platform adapter for Hermes Agent.

Implements the three abstract methods of ``BasePlatformAdapter`` (``connect``,
``disconnect``, ``send``) on top of the relay transport.

Deliberately *not* here, unlike the OpenClaw original's 997-line gateway file:
slash-command interception (Hermes owns commands), DM policy (Hermes owns
pairing and allowlists), and outbound chunking (the registry's
``max_message_length`` drives it centrally).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from .config import PLATFORM_NAME, KakaoConfig, load_config
from .hermes_compat import BasePlatformAdapter, MessageEvent, MessageType, SendResult
from .kakao.markdown import strip_markdown
from .kakao.response import build_simple_text_response
from .transport.client import RelayClientConfig, RelayHttpError, health_check, send_reply
from .transport.models import InboundMessage
from .transport.relay import StreamCallbacks, start_relay_stream
from .transport.session_store import load_session_token
from .transport.sse import SSESessionInvalidatedError

logger = logging.getLogger(__name__)


class KakaoAdapter(BasePlatformAdapter):  # type: ignore[misc,valid-type]
    """Bridges the KakaoTalk relay stream to the Hermes gateway."""

    def __init__(self, config: Any, platform: Any = None) -> None:
        super().__init__(config, platform)

        extra = getattr(config, "extra", None) or {}
        self.kakao_config: KakaoConfig = load_config(extra)

        # A token persisted after a previous pairing behaves like a configured
        # session token, which is where the original's resolution order put it.
        if not self.kakao_config.session_token:
            stored = load_session_token()
            if stored:
                self.kakao_config.session_token = stored

        self._stop_event = asyncio.Event()
        self._stream_task: asyncio.Task[None] | None = None
        self._relay_token: str | None = None
        self._relay_url: str = self.kakao_config.relay_url
        self._pairing_code: str | None = None
        # message id of the last inbound message per chat, so `send` knows which
        # relay message a reply belongs to.
        self._last_message_id: dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------

    async def connect(self, *, is_reconnect: bool = False) -> bool:
        """Start the relay stream. Returns True once the task is running."""
        if self._stream_task and not self._stream_task.done():
            return True

        # A cold boot starts from a clean slate; a reconnect keeps whatever the
        # relay still has queued for our Last-Event-ID.
        if not is_reconnect:
            self._stop_event = asyncio.Event()

        callbacks = StreamCallbacks(
            on_pairing_required=self._on_pairing_required,
            on_pairing_complete=self._on_pairing_complete,
            on_pairing_expired=self._on_pairing_expired,
            on_token_resolved=self._on_token_resolved,
            on_session_invalidated=self._on_session_invalidated,
            on_connected=self._mark_connected,
            on_disconnected=self._mark_disconnected,
        )

        self._stream_task = asyncio.create_task(
            self._run_stream(callbacks), name="kakao-relay-stream"
        )
        return True

    async def _run_stream(self, callbacks: StreamCallbacks) -> None:
        try:
            await start_relay_stream(
                config=self.kakao_config,
                on_message=self._on_inbound_message,
                stop_event=self._stop_event,
                callbacks=callbacks,
                channel_id=self.kakao_config.channel_id or "default",
            )
        except asyncio.CancelledError:
            raise
        except SSESessionInvalidatedError as error:
            self._set_fatal_error(
                "session_invalidated",
                f"Relay rejected the session token (HTTP {error.status}). Re-pair to continue.",
                retryable=True,
            )
        except Exception as error:  # noqa: BLE001
            logger.exception("[kakao] Relay stream terminated")
            self._set_fatal_error("relay_stream_failed", str(error), retryable=True)

    async def disconnect(self) -> None:
        self._stop_event.set()

        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
            # The task may fail on the way down; shutdown must still complete.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stream_task

        self._stream_task = None
        self._mark_disconnected()

    # -- inbound -----------------------------------------------------------

    async def _on_inbound_message(self, message: InboundMessage) -> None:
        """Normalize a relay message and hand it to the Hermes core."""
        user_id = message.normalized.user_id
        if not user_id:
            logger.warning("[kakao] Dropping inbound message %s: no userId", message.id)
            return

        if not self._is_allowed(user_id):
            logger.info("[kakao] Ignoring message from unauthorized user %s", user_id)
            return

        self._last_message_id[user_id] = message.id

        source = self.build_source(
            chat_id=user_id,
            chat_type="dm",
            user_id=user_id,
            user_name=user_id,
            chat_name=message.normalized.channel_id or PLATFORM_NAME,
        )

        event = MessageEvent(
            text=message.normalized.text,
            message_type=MessageType.TEXT,
            source=source,
            raw_message=message.kakao_payload,
            message_id=message.id,
            metadata={
                "conversation_key": message.conversation_key,
                "created_at": message.created_at,
            },
            timestamp=time.time(),
        )

        await self.handle_message(event)

    def _is_allowed(self, user_id: str) -> bool:
        """Local allowlist check.

        Hermes' own pairing/allowlist gate still applies on top of this; the
        registry is told about ``KAKAO_ALLOWED_USERS`` via ``allowed_users_env``.
        """
        if self.kakao_config.allow_all_users:
            return True
        if not self.kakao_config.allow_from:
            return True
        return user_id in self.kakao_config.allow_from

    # -- outbound ----------------------------------------------------------

    async def send(
        self,
        chat_id: str,
        content: str,
        reply_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        """Push a reply back through the relay."""
        if not self._relay_token:
            return SendResult(
                success=False,
                error="Relay token not resolved yet; the stream is not connected",
                retryable=True,
            )

        message_id = reply_to or self._last_message_id.get(chat_id)
        if not message_id:
            return SendResult(
                success=False,
                error=f"No inbound relay message to reply to for chat {chat_id}",
                retryable=False,
            )

        text = strip_markdown(content)
        if self.kakao_config.response_prefix:
            text = f"{self.kakao_config.response_prefix}{text}"

        response = self._build_response(text, metadata)

        client_config = RelayClientConfig(
            relay_url=self._relay_url, relay_token=self._relay_token
        )

        try:
            result = await send_reply(client_config, message_id, response)
        except RelayHttpError as error:
            return SendResult(
                success=False,
                error=str(error),
                retryable=not error.is_auth_error,
            )
        except Exception as error:  # noqa: BLE001
            return SendResult(success=False, error=str(error), retryable=True)

        return SendResult(
            success=result.success,
            message_id=message_id,
            error=result.error,
            retryable=not result.success,
        )

    def _build_response(
        self, text: str, metadata: dict[str, Any] | None
    ) -> dict[str, Any]:
        """Build the Kakao skill response, honoring a channelData override.

        An agent can emit a fully-formed Kakao response by putting it at
        ``metadata["channel_data"]["kakao"]`` — the Python equivalent of the
        OpenClaw plugin's ``channelData.kakao`` pattern.
        """
        channel_data = (metadata or {}).get("channel_data") or {}
        kakao_override = channel_data.get("kakao")

        if isinstance(kakao_override, dict) and kakao_override.get("version") == "2.0":
            return kakao_override

        return build_simple_text_response(text)

    # -- health ------------------------------------------------------------

    async def probe(self) -> Any:
        """Relay reachability check, used by ``is_connected``/``hermes status``."""
        return await health_check(
            RelayClientConfig(relay_url=self._relay_url, relay_token=self._relay_token or "")
        )

    # -- callbacks ---------------------------------------------------------

    def _on_pairing_required(self, pairing_code: str, expires_in: int) -> None:
        self._pairing_code = pairing_code
        minutes = max(1, expires_in // 60)
        logger.warning(
            "[kakao] Pairing required. Send this code to your KakaoTalk channel "
            "within %s minute(s): %s",
            minutes,
            pairing_code,
        )

    def _on_pairing_complete(self, kakao_user_id: str) -> None:
        self._pairing_code = None
        logger.info("[kakao] Paired with KakaoTalk user %s", kakao_user_id)

    def _on_pairing_expired(self, reason: str) -> None:
        self._pairing_code = None
        logger.warning("[kakao] Pairing expired: %s", reason)

    def _on_token_resolved(self, token: str, relay_url: str) -> None:
        self._relay_token = token
        self._relay_url = relay_url

    def _on_session_invalidated(self, status: int) -> None:
        self._relay_token = None
        self.kakao_config.session_token = None

    @property
    def pending_pairing_code(self) -> str | None:
        return self._pairing_code
