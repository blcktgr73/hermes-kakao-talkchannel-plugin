from __future__ import annotations

import pytest

from hermes_kakao_talkchannel.kakao.payload import (
    MAX_UTTERANCE_LENGTH,
    extract_user_id,
    extract_utterance,
    get_callback_url,
    has_callback_url,
    parse_kakao_user,
    parse_skill_payload,
)
from tests.fixtures.payloads import minimal_payload, valid_payload


def test_valid_payload_parses_and_returns_same_object() -> None:
    payload = valid_payload()
    assert parse_skill_payload(payload) is payload


@pytest.mark.parametrize("body", [None, "string", 42, True])
def test_non_object_body_is_rejected(body: object) -> None:
    with pytest.raises(ValueError, match="SkillPayload must be an object"):
        parse_skill_payload(body)


@pytest.mark.parametrize("field", ["intent", "userRequest", "bot", "action"])
def test_missing_top_level_field_is_rejected(field: str) -> None:
    payload = valid_payload()
    del payload[field]
    with pytest.raises(ValueError, match=f"SkillPayload missing required field: {field}"):
        parse_skill_payload(payload)


def test_missing_utterance_is_rejected() -> None:
    payload = valid_payload()
    del payload["userRequest"]["utterance"]
    with pytest.raises(ValueError, match="userRequest missing required field: utterance"):
        parse_skill_payload(payload)


@pytest.mark.parametrize("utterance", ["   ", "\n"])
def test_blank_utterance_is_rejected(utterance: str) -> None:
    payload = valid_payload()
    payload["userRequest"]["utterance"] = utterance
    with pytest.raises(ValueError, match="must be a non-empty string"):
        parse_skill_payload(payload)


def test_oversized_utterance_is_rejected() -> None:
    payload = valid_payload()
    payload["userRequest"]["utterance"] = "가" * (MAX_UTTERANCE_LENGTH + 1)
    with pytest.raises(ValueError, match="exceeds maximum length"):
        parse_skill_payload(payload)


def test_utterance_at_the_limit_is_accepted() -> None:
    payload = valid_payload()
    payload["userRequest"]["utterance"] = "가" * MAX_UTTERANCE_LENGTH
    assert parse_skill_payload(payload) is payload


def test_missing_user_id_is_rejected() -> None:
    payload = valid_payload()
    del payload["userRequest"]["user"]["id"]
    with pytest.raises(ValueError, match="userRequest.user missing required field: id"):
        parse_skill_payload(payload)


def test_extract_user_id() -> None:
    assert extract_user_id(valid_payload()) == "botuserkey-abc123"


def test_extract_utterance_is_not_trimmed() -> None:
    payload = valid_payload()
    payload["userRequest"]["utterance"] = "  띄어쓰기  "
    assert extract_utterance(payload) == "  띄어쓰기  "


def test_parse_kakao_user_full_properties() -> None:
    user = parse_kakao_user(valid_payload())
    assert user.bot_user_key == "botuserkey-abc123"
    assert user.plusfriend_user_key == "plusfriend-xyz"
    assert user.is_friend is True


def test_parse_kakao_user_defaults_when_properties_absent() -> None:
    user = parse_kakao_user(minimal_payload())
    assert user.bot_user_key == "botuserkey-minimal"
    assert user.plusfriend_user_key is None
    assert user.is_friend is False


def test_callback_url_helpers() -> None:
    payload = valid_payload()
    assert has_callback_url(payload) is True
    assert get_callback_url(payload) == "https://callback.kakao.example/v1/callback/abc"


def test_callback_url_absent() -> None:
    payload = minimal_payload()
    assert has_callback_url(payload) is False
    assert get_callback_url(payload) is None


def test_blank_callback_url_counts_as_absent() -> None:
    payload = valid_payload()
    payload["userRequest"]["callbackUrl"] = "   "
    assert get_callback_url(payload) is None
