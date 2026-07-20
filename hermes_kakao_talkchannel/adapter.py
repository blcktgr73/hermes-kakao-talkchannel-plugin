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
import os
import time
from collections import defaultdict, deque
from dataclasses import replace
from typing import Any

from .config import PLATFORM_NAME, KakaoConfig, load_config
from .hermes_compat import (
    BasePlatformAdapter,
    MessageEvent,
    MessageType,
    Platform,
    SendResult,
)
from .kakao.markdown import strip_markdown
from .kakao.response import build_simple_text_response
from .pairing.publisher import PairingPublisher
from .pairing.registry import (
    PairingSnapshot,
    add_pairing_waiter,
    record_pairing_complete,
    record_pairing_expired,
    record_pairing_required,
    record_session_invalidated,
    record_session_reused,
    register_account,
    unregister_account,
)
from .transport.client import RelayClientConfig, RelayHttpError, health_check, send_reply
from .transport.models import InboundMessage
from .transport.relay import (
    LEGACY_RELAY_TOKEN_ENV,
    RELAY_TOKEN_ENV,
    StreamCallbacks,
    start_relay_stream,
)
from .transport.session_store import forget_session_token, load_session_token
from .transport.sse import SSESessionInvalidatedError

logger = logging.getLogger(__name__)

#: Transient acknowledgements Hermes emits when a message arrives mid-run
#: (``gateway/run.py``). They are informational and always followed by the real
#: answer.
#:
#: KakaoTalk gives exactly **one single-use callback per inbound message**, so
#: whichever send goes first consumes it and everything after fails with
#: "Callback URL expired or not available". Observed on a live gateway
#: 2026-07-20: sending a second message while a run was active delivered the
#: ack and then lost the answer entirely.
#:
#: Spending that one callback on "I'll respond shortly" instead of the response
#: is the wrong trade on this platform, so these are dropped. Set
#: ``KAKAO_SEND_STATUS_NOTICES=1`` to send them anyway.
#: How long a Kakao callback URL stays usable. The relay documents 55s; a
#: little margin keeps us from claiming an id that is about to die mid-flight.
CALLBACK_TTL_SECONDS = 50.0

_TRANSIENT_ACK_PREFIXES = (
    "⚡ Interrupting current task",
    "⏳ Queued for the next turn",
    "⏳ Subagent working",
    "⏳ Compressing context",
    "⏩ Steered into current run",
    # Meta-messages about the transport itself. Announcing that delivery failed
    # *over the delivery that failed* is circular, and worse: each attempt burns
    # another callback, so the notice crowds out the answer it is apologising
    # for. Observed on the VM as a runaway loop — three user messages produced
    # 24 sends, most of them delivery-failure notices about earlier
    # delivery-failure notices.
    "⚠️ Message delivery failed",
    "⚠️ Your message was interrupted before processing started",
)


class KakaoAdapter(BasePlatformAdapter):  # type: ignore[misc,valid-type]
    """Bridges the KakaoTalk relay stream to the Hermes gateway."""

    def __init__(self, config: Any, platform: Any = None) -> None:
        # The adapter builds its own Platform value, matching the bundled LINE
        # adapter. `Platform._missing_` mints a pseudo-member for any name the
        # registry already knows, so this only works *after* register_platform
        # has run — which is the real ordering, since the registry constructs
        # adapters. If it raises, the registration order is wrong and we want
        # to hear about it rather than silently run without a platform.
        if platform is None and Platform is not None:
            platform = Platform(PLATFORM_NAME)

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
        # Unused inbound message ids per chat, oldest first.
        #
        # Each inbound message carries exactly one single-use Kakao callback, so
        # a message id may back at most one reply. An earlier version kept a
        # single "last id" per chat: two messages arriving before the first
        # answer overwrote it, so one reply targeted a spent callback and was
        # lost (observed 2026-07-20 — `ping 02` and `ping 03` in the same
        # second, both answers failing with "Kakao callback failed").
        self._pending_message_ids: dict[str, deque[tuple[str, float]]] = defaultdict(deque)
        #: Monotonic counter so the log shows how many sends one turn produced.
        self._send_seq = 0

        self._account_id = self.kakao_config.channel_id or "default"
        # Supervisor state for re-issuing a pairing code without restarting the
        # gateway: a request aborts the inner stream and the loop runs again
        # with the saved session token stripped.
        self._inner_stop = asyncio.Event()
        self._reissue_requested = False
        self._running = False
        self._publisher = PairingPublisher()

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

        self._running = True
        register_account(self._account_id, self._account_id, self)
        # The CLI runs in a different process and Hermes has no channel into a
        # running gateway, so state is published to disk and re-issue requests
        # are polled from it.
        self._publisher.start()

        self._stream_task = asyncio.create_task(
            self._run_stream(callbacks), name="kakao-relay-stream"
        )
        return True

    async def _run_stream(self, callbacks: StreamCallbacks) -> None:
        """Supervise the relay stream, restarting it for a forced re-issue."""
        try:
            while not self._stop_event.is_set():
                # On a forced re-issue the saved token must not come back through
                # config, or resolve_token short-circuits before create_session
                # and no new code is ever issued.
                config = self.kakao_config
                if self._reissue_requested:
                    config = replace(config, session_token=None)
                elif config.session_token:
                    record_session_reused(self._account_id, self._account_id)

                self._reissue_requested = False
                # One event drives the stream. `disconnect` sets both this and
                # the outer stop, so there is no second signal to combine.
                self._inner_stop = asyncio.Event()

                try:
                    await start_relay_stream(
                        config=config,
                        on_message=self._on_inbound_message,
                        stop_event=self._inner_stop,
                        callbacks=callbacks,
                        channel_id=self._account_id,
                    )
                except SSESessionInvalidatedError as error:
                    if self._stop_event.is_set():
                        return
                    self._set_fatal_error(
                        "session_invalidated",
                        f"Relay rejected the session token (HTTP {error.status}). "
                        "Re-pair to continue.",
                        retryable=True,
                    )
                    return
                except Exception as error:  # noqa: BLE001
                    if self._stop_event.is_set():
                        return
                    # A re-issue aborts the stream on purpose; anything else is real.
                    if not self._reissue_requested:
                        logger.exception("[kakao] Relay stream terminated")
                        self._set_fatal_error(
                            "relay_stream_failed", str(error), retryable=True
                        )
                        return

                if self._stop_event.is_set():
                    return
                # The stream ended on its own and no re-issue is pending.
                if not self._reissue_requested:
                    return
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False
            unregister_account(self._account_id)
            await self._publisher.stop()

    # -- AccountController -------------------------------------------------

    def reissue_blocked_reason(self) -> str | None:
        """A static token means resolve_token never calls create_session."""
        if not self._running:
            return "account is not running"
        if self.kakao_config.relay_token:
            return (
                "This account uses a configured relay token, so it never pairs. "
                "Unset KAKAO_RELAY_TOKEN to use pairing."
            )
        for env_name in (RELAY_TOKEN_ENV, LEGACY_RELAY_TOKEN_ENV):
            if os.environ.get(env_name):
                return f"{env_name} is set, so this account never pairs. Unset it to pair."
        return None

    async def request_new_pairing(self, timeout_seconds: float) -> PairingSnapshot:
        """Drop the current session and wait for a fresh code. No restart."""
        logger.info("[kakao] Re-issuing pairing code on request")

        # Drop every copy of the current token, or resolve_token reuses it.
        forget_session_token(self._account_id)
        self.kakao_config.session_token = None
        self._relay_token = None
        record_session_invalidated(self._account_id, self._account_id)

        loop = asyncio.get_running_loop()
        future: asyncio.Future[PairingSnapshot] = loop.create_future()

        def on_issued(snapshot: PairingSnapshot) -> None:
            if not future.done():
                loop.call_soon_threadsafe(future.set_result, snapshot)

        # Start waiting before triggering, so a fast relay cannot answer first.
        cancel_waiter = add_pairing_waiter(self._account_id, on_issued)
        self._reissue_requested = True
        self._inner_stop.set()

        try:
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        except TimeoutError as error:
            raise RuntimeError(
                f"Timed out after {timeout_seconds:.0f}s waiting for a pairing code"
            ) from error
        finally:
            cancel_waiter()

    async def disconnect(self) -> None:
        self._stop_event.set()
        # The supervisor waits on the inner event, so it must be released too.
        self._inner_stop.set()

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

        self._pending_message_ids[user_id].append((message.id, time.time()))

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
        # WARNING, not INFO, on purpose while bringing this up: the host filters
        # plugin INFO, and "how many times did the core call send for one turn,
        # and with what" is the one question the gateway's own logs cannot
        # answer — they show failed deliveries, not the calls that caused them.
        # Drop to INFO once the outbound shape is settled.
        preview = (content or "").replace("\n", " ")[:80]
        logger.warning(
            "[kakao] send #%d chat=%s len=%d reply_to=%s preview=%r",
            self._send_seq,
            chat_id,
            len(content or ""),
            reply_to,
            preview,
        )
        self._send_seq += 1

        if self._is_transient_ack(content):
            logger.warning("[kakao] send #%d dropped: transport meta-message", self._send_seq - 1)
            return SendResult(success=True)

        if not self._relay_token:
            return SendResult(
                success=False,
                error="Relay token not resolved yet; the stream is not connected",
                retryable=True,
            )

        # `reply_to` is deliberately ignored for callback selection.
        #
        # It is a *threading* hint — Hermes passes the originating message id
        # per `reply_to_mode` (default "first") so platforms that thread can
        # attach the reply. KakaoTalk has no threading, and its callbacks are
        # single use, so honouring it meant every reply in a turn targeted the
        # same already-spent callback. The relay log made this unambiguous:
        # every failure carried one messageId and one cbtoken, retried until
        # Kakao answered 400. The queue is the only correct source here.
        message_id = self._take_message_id(chat_id)
        if not message_id:
            return SendResult(
                success=False,
                error=(
                    f"No unused inbound message to reply to for chat {chat_id}. "
                    "Every KakaoTalk callback is single use, so a reply needs its "
                    "own inbound message and one may already have expired."
                ),
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

    def _take_message_id(self, chat_id: str) -> str | None:
        """Claim the oldest unused inbound message id for this chat.

        Consuming rather than peeking is the point: a Kakao callback works once,
        so two replies must never target the same inbound message. Entries older
        than the callback TTL are dropped first — their callbacks are already
        dead and using one would fail with "Callback URL expired".
        """
        pending = self._pending_message_ids.get(chat_id)
        if not pending:
            return None

        cutoff = time.time() - CALLBACK_TTL_SECONDS
        while pending and pending[0][1] < cutoff:
            expired_id, _ = pending.popleft()
            logger.debug("[kakao] Dropping expired callback for message %s", expired_id)

        if not pending:
            return None
        message_id, _ = pending.popleft()
        return message_id

    @staticmethod
    def _is_transient_ack(content: str) -> bool:
        """Whether this is a mid-run status notice rather than an answer.

        Reported as delivered without spending the callback. The alternative on
        KakaoTalk is not "notice plus answer" — it is "notice instead of
        answer", because the callback is single use.
        """
        if os.environ.get("KAKAO_SEND_STATUS_NOTICES", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return False
        stripped = (content or "").lstrip()
        return any(stripped.startswith(prefix) for prefix in _TRANSIENT_ACK_PREFIXES)

    async def get_chat_info(self, chat_id: str) -> dict[str, Any]:
        """Chat metadata for the agent. Abstract on the real base class.

        A KakaoTalk Channel conversation is always 1:1 and the relay gives us
        no display name — the botUserKey is all there is. Best effort, matching
        how the bundled LINE adapter answers this.
        """
        return {"name": chat_id or "", "type": "dm"}

    # -- health ------------------------------------------------------------

    async def probe(self) -> Any:
        """Relay reachability check, used by ``is_connected``/``hermes status``."""
        return await health_check(
            RelayClientConfig(relay_url=self._relay_url, relay_token=self._relay_token or "")
        )

    # -- callbacks ---------------------------------------------------------

    def _on_pairing_required(self, pairing_code: str, expires_in: int) -> None:
        self._pairing_code = pairing_code
        record_pairing_required(self._account_id, self._account_id, pairing_code, expires_in)

        minutes = max(1, expires_in // 60)
        logger.warning(
            "[kakao] Pairing required. Send this code to your KakaoTalk channel "
            "within %s minute(s): %s",
            minutes,
            pairing_code,
        )
        logger.warning("[kakao] Re-read it any time: hermes kakao pairing status")

    def _on_pairing_complete(self, kakao_user_id: str) -> None:
        # The relay sends this ~4x in 2s. Without the dedupe each one would
        # repeat the side effects below.
        if not record_pairing_complete(self._account_id, self._account_id, kakao_user_id):
            return
        self._pairing_code = None
        logger.info("[kakao] Paired with KakaoTalk user %s", kakao_user_id)

    def _on_pairing_expired(self, reason: str) -> None:
        self._pairing_code = None
        record_pairing_expired(self._account_id, self._account_id)
        logger.warning("[kakao] Pairing expired: %s", reason)

    def _on_token_resolved(self, token: str, relay_url: str) -> None:
        self._relay_token = token
        self._relay_url = relay_url

    def _on_session_invalidated(self, status: int) -> None:
        self._relay_token = None
        self.kakao_config.session_token = None
        record_session_invalidated(self._account_id, self._account_id)

    @property
    def pending_pairing_code(self) -> str | None:
        return self._pairing_code
