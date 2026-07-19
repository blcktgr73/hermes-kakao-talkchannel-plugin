from __future__ import annotations

import pytest

from hermes_kakao_talkchannel.config import KakaoConfig, load_config, validate_config
from hermes_kakao_talkchannel.transport.session import DEFAULT_RELAY_URL


def test_defaults_match_the_original_plugin() -> None:
    config = load_config({})
    assert config.enabled is True
    assert config.relay_url == DEFAULT_RELAY_URL
    assert config.text_chunk_limit == 400
    assert config.chunk_mode == "sentence"
    assert config.reconnect_delay_ms == 1000
    assert config.max_reconnect_delay_ms == 30000
    assert config.allow_from == []
    assert config.allow_all_users is False


def test_yaml_extra_is_applied() -> None:
    config = load_config({"relay_url": "https://my-relay.example/", "response_prefix": "[봇] "})
    assert config.relay_url == "https://my-relay.example/"
    assert config.response_prefix == "[봇] "


def test_camel_case_keys_are_accepted_for_openclaw_compatibility() -> None:
    config = load_config({"relayUrl": "https://camel.example/", "textChunkLimit": 250})
    assert config.relay_url == "https://camel.example/"
    assert config.text_chunk_limit == 250


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://env.example/")
    config = load_config({"relay_url": "https://yaml.example/"})
    assert config.relay_url == "https://env.example/"


def test_allowed_users_env_is_split_and_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_ALLOWED_USERS", " user-a , user-b ,, user-c ")
    assert load_config({}).allow_from == ["user-a", "user-b", "user-c"]


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_allow_all_users_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("KAKAO_ALLOW_ALL_USERS", value)
    assert load_config({}).allow_all_users is True


@pytest.mark.parametrize("value", ["0", "false", "no", ""])
def test_allow_all_users_falsy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("KAKAO_ALLOW_ALL_USERS", value)
    assert load_config({}).allow_all_users is False


def test_invalid_chunk_mode_from_env_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_CHUNK_MODE", "nonsense")
    assert load_config({}).chunk_mode == "sentence"


def test_non_numeric_chunk_limit_from_env_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_TEXT_CHUNK_LIMIT", "abc")
    assert load_config({}).text_chunk_limit == 400


# -- validation ------------------------------------------------------------


def test_default_config_validates() -> None:
    assert validate_config(KakaoConfig()).ok is True


@pytest.mark.parametrize("limit", [99, 1001])
def test_chunk_limit_range(limit: int) -> None:
    result = validate_config(KakaoConfig(text_chunk_limit=limit))
    assert result.ok is False
    assert any("text_chunk_limit" in error for error in result.errors)


@pytest.mark.parametrize("delay", [499, 10001])
def test_reconnect_delay_range(delay: int) -> None:
    result = validate_config(KakaoConfig(reconnect_delay_ms=delay))
    assert result.ok is False
    assert any("reconnect_delay_ms" in error for error in result.errors)


@pytest.mark.parametrize("delay", [4999, 60001])
def test_max_reconnect_delay_range(delay: int) -> None:
    result = validate_config(KakaoConfig(max_reconnect_delay_ms=delay))
    assert result.ok is False
    assert any("max_reconnect_delay_ms" in error for error in result.errors)


def test_missing_relay_url_is_an_error() -> None:
    result = validate_config(KakaoConfig(relay_url=""))
    assert result.ok is False
    assert "relay_url is required" in result.errors


def test_multiple_errors_are_all_reported() -> None:
    result = validate_config(KakaoConfig(relay_url="", text_chunk_limit=5, chunk_mode="bogus"))
    assert len(result.errors) == 3
