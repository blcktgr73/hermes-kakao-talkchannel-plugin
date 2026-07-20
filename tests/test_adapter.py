from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from hermes_kakao_talkchannel.adapter import KakaoAdapter
from hermes_kakao_talkchannel.transport import client as client_module
from hermes_kakao_talkchannel.transport.client import RelayHttpError
from hermes_kakao_talkchannel.transport.models import InboundMessage, SendReplyResponse
from tests.fixtures.payloads import inbound_wire


@dataclass
class FakePlatformConfig:
    enabled: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@pytest.fixture()
def adapter(isolated_state_dir: Any) -> KakaoAdapter:
    instance = KakaoAdapter(FakePlatformConfig(extra={"relay_url": "https://relay.example/"}))
    instance._relay_token = "tok-test"
    return instance


@pytest.fixture()
def captured_events(adapter: KakaoAdapter) -> list[Any]:
    events: list[Any] = []

    async def handler(event: Any) -> None:
        events.append(event)

    adapter.set_message_handler(handler)
    return events


# -- inbound ---------------------------------------------------------------


async def test_inbound_message_becomes_a_message_event(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))

    assert len(captured_events) == 1
    event = captured_events[0]
    assert event.text == "안녕하세요"
    assert event.message_id == "msg-0001"
    assert event.source.chat_id == "botuserkey-abc123"
    assert event.source.chat_type == "dm"
    assert event.source.user_id == "botuserkey-abc123"
    assert event.metadata["conversation_key"] == "conv-abc"


async def test_inbound_message_records_the_reply_target(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))
    assert adapter._last_message_id["botuserkey-abc123"] == "msg-0001"


async def test_message_without_a_user_id_is_dropped(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    wire = inbound_wire()
    wire["normalized"]["userId"] = ""
    await adapter._on_inbound_message(InboundMessage.from_wire(wire))
    assert captured_events == []


async def test_allowlist_blocks_unlisted_users(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    adapter.kakao_config.allow_from = ["someone-else"]
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))
    assert captured_events == []


async def test_allowlist_permits_listed_users(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    adapter.kakao_config.allow_from = ["botuserkey-abc123"]
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))
    assert len(captured_events) == 1


async def test_allow_all_overrides_the_allowlist(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    adapter.kakao_config.allow_from = ["someone-else"]
    adapter.kakao_config.allow_all_users = True
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))
    assert len(captured_events) == 1


async def test_an_empty_allowlist_permits_everyone(
    adapter: KakaoAdapter, captured_events: list[Any]
) -> None:
    # Hermes' own pairing gate is what restricts DMs by default; the plugin's
    # local list is an additional filter, not the primary one.
    assert adapter.kakao_config.allow_from == []
    await adapter._on_inbound_message(InboundMessage.from_wire(inbound_wire()))
    assert len(captured_events) == 1


# -- outbound --------------------------------------------------------------


async def test_send_fails_before_the_token_is_resolved(adapter: KakaoAdapter) -> None:
    adapter._relay_token = None
    result = await adapter.send("botuserkey-abc123", "안녕")
    assert result.success is False
    assert result.retryable is True
    assert result.error is not None
    assert "not resolved" in result.error


async def test_send_fails_without_an_inbound_message_to_reply_to(
    adapter: KakaoAdapter,
) -> None:
    result = await adapter.send("unknown-user", "안녕")
    assert result.success is False
    assert result.retryable is False


async def test_send_posts_a_simple_text_response(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    async def fake_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        sent.append((message_id, response))
        return SendReplyResponse(success=True)

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)

    adapter._last_message_id["botuserkey-abc123"] = "msg-0001"
    result = await adapter.send("botuserkey-abc123", "안녕")

    assert result.success is True
    assert sent[0][0] == "msg-0001"
    assert sent[0][1] == {
        "version": "2.0",
        "template": {"outputs": [{"simpleText": {"text": "안녕"}}]},
    }


async def test_send_strips_markdown(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        sent.append(response)
        return SendReplyResponse(success=True)

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)

    adapter._last_message_id["u"] = "m"
    await adapter.send("u", "**굵게** 그리고 `코드`")

    assert sent[0]["template"]["outputs"][0]["simpleText"]["text"] == "굵게 그리고 코드"


async def test_send_applies_the_response_prefix(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        sent.append(response)
        return SendReplyResponse(success=True)

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)

    adapter.kakao_config.response_prefix = "[봇] "
    adapter._last_message_id["u"] = "m"
    await adapter.send("u", "안녕")

    assert sent[0]["template"]["outputs"][0]["simpleText"]["text"] == "[봇] 안녕"


async def test_channel_data_override_replaces_the_whole_response(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        sent.append(response)
        return SendReplyResponse(success=True)

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)

    override = {
        "version": "2.0",
        "template": {"outputs": [{"textCard": {"title": "카드"}}]},
    }
    adapter._last_message_id["u"] = "m"
    await adapter.send("u", "무시됨", metadata={"channel_data": {"kakao": override}})

    assert sent[0] == override


async def test_auth_errors_are_reported_as_non_retryable(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        raise RelayHttpError(401, "Unauthorized", "token expired")

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", failing_send_reply)

    adapter._last_message_id["u"] = "m"
    result = await adapter.send("u", "안녕")

    assert result.success is False
    assert result.retryable is False


async def test_server_errors_are_reported_as_retryable(
    adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_send_reply(config: Any, message_id: str, response: dict[str, Any]) -> Any:
        raise RelayHttpError(503, "Service Unavailable", "down")

    monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", failing_send_reply)

    adapter._last_message_id["u"] = "m"
    result = await adapter.send("u", "안녕")

    assert result.success is False
    assert result.retryable is True


# -- lifecycle -------------------------------------------------------------


async def test_disconnect_is_safe_before_connect(adapter: KakaoAdapter) -> None:
    await adapter.disconnect()
    assert adapter._stream_task is None


async def test_stored_session_token_is_picked_up(isolated_state_dir: Any) -> None:
    from hermes_kakao_talkchannel.transport.session_store import persist_session_token

    persist_session_token("stored-token")
    instance = KakaoAdapter(FakePlatformConfig())
    assert instance.kakao_config.session_token == "stored-token"


async def test_pairing_callbacks_track_the_code(adapter: KakaoAdapter) -> None:
    adapter._on_pairing_required("ABCD1234", 3600)
    assert adapter.pending_pairing_code == "ABCD1234"

    adapter._on_pairing_complete("kakao-user-1")
    assert adapter.pending_pairing_code is None


async def test_session_invalidation_clears_the_token(adapter: KakaoAdapter) -> None:
    adapter._on_session_invalidated(401)
    assert adapter._relay_token is None
    assert adapter.kakao_config.session_token is None


class TestTransientAckSuppression:
    """KakaoTalk gives one single-use callback per inbound message.

    Observed on a live gateway 2026-07-20: a second message arriving mid-run
    made Hermes emit "⚡ Interrupting current task", that ack consumed the
    callback, and the actual answer then failed with "Callback URL expired or
    not available". On this platform the choice is not "notice and answer" but
    "notice instead of answer".
    """

    @pytest.mark.parametrize(
        "content",
        [
            "⚡ Interrupting current task. I'll respond to your message shortly.",
            "⏳ Queued for the next turn. I'll respond once the current task finishes.",
            "⏳ Subagent working — your message is queued.",
            "⏳ Compressing context — your message is queued.",
            "⏩ Steered into current run. Your message arrives after the next tool call.",
        ],
    )
    async def test_transient_notices_do_not_spend_the_callback(
        self, adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch, content: str
    ) -> None:
        sent: list[str] = []

        async def fake_send_reply(config: Any, message_id: str, response: Any) -> Any:
            sent.append(message_id)
            return SendReplyResponse(success=True)

        monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)
        adapter._last_message_id["u"] = "m"

        result = await adapter.send("u", content)

        # Reported as delivered so the core does not retry, but nothing is sent.
        assert result.success is True
        assert sent == []

    async def test_a_real_answer_still_sends(
        self, adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[str] = []

        async def fake_send_reply(config: Any, message_id: str, response: Any) -> Any:
            sent.append(message_id)
            return SendReplyResponse(success=True)

        monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)
        adapter._last_message_id["u"] = "m"

        await adapter.send("u", "pong 01")

        assert sent == ["m"]

    async def test_an_answer_merely_mentioning_a_prefix_still_sends(
        self, adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Matching is anchored at the start, so ordinary prose is unaffected.
        sent: list[str] = []

        async def fake_send_reply(config: Any, message_id: str, response: Any) -> Any:
            sent.append(message_id)
            return SendReplyResponse(success=True)

        monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)
        adapter._last_message_id["u"] = "m"

        await adapter.send("u", "The bot said ⚡ Interrupting current task earlier.")

        assert sent == ["m"]

    async def test_opt_in_restores_the_notices(
        self, adapter: KakaoAdapter, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[str] = []

        async def fake_send_reply(config: Any, message_id: str, response: Any) -> Any:
            sent.append(message_id)
            return SendReplyResponse(success=True)

        monkeypatch.setattr("hermes_kakao_talkchannel.adapter.send_reply", fake_send_reply)
        monkeypatch.setenv("KAKAO_SEND_STATUS_NOTICES", "1")
        adapter._last_message_id["u"] = "m"

        await adapter.send("u", "⚡ Interrupting current task. I'll respond shortly.")

        assert sent == ["m"]


async def test_get_chat_info_reports_a_dm(adapter: KakaoAdapter) -> None:
    # Abstract on the real base class (verified against hermes-agent 0.18.2).
    # A KakaoTalk Channel conversation is always 1:1.
    info = await adapter.get_chat_info("botuserkey-abc123")
    assert info == {"name": "botuserkey-abc123", "type": "dm"}


async def test_get_chat_info_tolerates_a_blank_chat_id(adapter: KakaoAdapter) -> None:
    assert await adapter.get_chat_info("") == {"name": "", "type": "dm"}


def test_adapter_implements_every_abstract_method() -> None:
    """Guards the failure that shipped: a missing abstract method.

    `get_chat_info` was abstract on the real base class but the local stub was
    a plain class, so the omission passed every test here and would have
    failed at adapter construction on a real gateway. The stub is now an ABC;
    this test states the invariant directly so the reason survives.
    """
    from hermes_kakao_talkchannel.hermes_compat import BasePlatformAdapter

    required = set(getattr(BasePlatformAdapter, "__abstractmethods__", ()))
    missing = {name for name in required if getattr(KakaoAdapter, name, None) is None}
    assert not missing, f"KakaoAdapter does not implement: {sorted(missing)}"
    assert not getattr(KakaoAdapter, "__abstractmethods__", ())


def test_unused_import_guard() -> None:
    # client_module is imported to keep the relay client's import path exercised
    # even when every send is monkeypatched.
    assert client_module.DEFAULT_TIMEOUT_MS == 10000
