from __future__ import annotations

from typing import Any

import pytest

from hermes_kakao_talkchannel import register
from hermes_kakao_talkchannel.registration import (
    apply_yaml_config,
    env_enablement,
    is_connected,
    validate_config,
)


class FakeContext:
    """Stand-in for Hermes' PluginContext, capturing the registration calls."""

    def __init__(self) -> None:
        self.platforms: list[dict[str, Any]] = []
        self.cli_commands: list[dict[str, Any]] = []

    def register_platform(self, **kwargs: Any) -> None:
        self.platforms.append(kwargs)

    def register_cli_command(self, **kwargs: Any) -> None:
        self.cli_commands.append(kwargs)


def test_register_registers_exactly_one_platform() -> None:
    ctx = FakeContext()
    register(ctx)
    assert len(ctx.platforms) == 1


def test_registered_platform_identity() -> None:
    ctx = FakeContext()
    register(ctx)
    entry = ctx.platforms[0]
    assert entry["name"] == "kakaotalk"
    assert entry["label"] == "KakaoTalk"
    assert entry["max_message_length"] == 1000
    assert entry["allowed_users_env"] == "KAKAO_ALLOWED_USERS"
    assert entry["allow_all_env"] == "KAKAO_ALLOW_ALL_USERS"


def test_adapter_factory_builds_an_adapter() -> None:
    from hermes_kakao_talkchannel.adapter import KakaoAdapter

    ctx = FakeContext()
    register(ctx)

    class Cfg:
        extra: dict[str, Any] = {}

    adapter = ctx.platforms[0]["adapter_factory"](Cfg())
    assert isinstance(adapter, KakaoAdapter)


class Cfg:
    """Stand-in for PlatformConfig."""

    def __init__(self, extra: dict[str, Any] | None = None) -> None:
        self.extra = extra or {}


# `is_connected` receives a PlatformConfig, not an adapter, and answers "would
# this be configured if enabled?" — the gateway uses it to decide auto-enable.
# An earlier version took an adapter and read `_connected`, so it returned
# False for every config and the platform could never enable.
def test_is_connected_without_a_config() -> None:
    assert is_connected(None) is False


def test_is_connected_false_on_defaults_alone() -> None:
    # relay_url always has a default; treating that as configuration would
    # auto-enable a channel that ships plaintext to a third-party relay.
    assert is_connected(Cfg()) is False


def test_is_connected_true_once_the_relay_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://relay.example/")
    assert is_connected(Cfg()) is True


@pytest.mark.parametrize(
    "env_name", ["KAKAO_RELAY_TOKEN", "KAKAO_SESSION_TOKEN", "KAKAO_CHANNEL_ID"]
)
def test_is_connected_true_for_any_explicit_env(
    monkeypatch: pytest.MonkeyPatch, env_name: str
) -> None:
    monkeypatch.setenv(env_name, "value")
    assert is_connected(Cfg()) is True


def test_is_connected_true_from_yaml_extra() -> None:
    assert is_connected(Cfg({"relay_url": "https://relay.example/"})) is True


# The registry tests this as `if not entry.validate_config(config)` and refuses
# to build the adapter on a falsy result. An earlier version returned a list of
# error strings, so the success case — an empty list — was falsy and the
# platform failed validation exactly when it was valid.
def test_validate_config_returns_a_bool_not_a_list() -> None:
    assert validate_config(Cfg({"relay_url": "https://relay.example/"})) is True


def test_validate_config_false_when_unconfigured() -> None:
    assert validate_config(Cfg()) is False


def test_validate_config_false_on_out_of_range_values() -> None:
    assert (
        validate_config(
            Cfg({"relay_url": "https://relay.example/", "text_chunk_limit": 5})
        )
        is False
    )


def test_validate_config_true_from_env_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://relay.example/")
    assert validate_config(Cfg()) is True


def test_env_enablement_seeds_extra_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://env-relay.example/")
    monkeypatch.setenv("KAKAO_RESPONSE_PREFIX", "[봇] ")

    extra = env_enablement()

    assert extra is not None
    assert extra["relay_url"] == "https://env-relay.example/"
    assert extra["response_prefix"] == "[봇] "


def test_env_enablement_is_none_when_nothing_is_configured() -> None:
    # Matches the bundled LINE and IRC plugins. Returning a dict here would
    # claim an env-only setup exists when no KakaoTalk variable is set.
    assert env_enablement() is None


def test_env_enablement_omits_absent_optional_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://relay.example/")

    extra = env_enablement()

    assert extra is not None
    assert extra["relay_url"] == "https://relay.example/"
    assert "relay_token" not in extra
    assert "response_prefix" not in extra
    assert "home_channel" not in extra


def test_apply_yaml_config_merges_extra() -> None:
    class PlatformConfig:
        extra = {"existing": 1}

    merged = apply_yaml_config({"extra": {"relay_url": "https://yaml.example/"}}, PlatformConfig())
    assert merged == {"existing": 1, "relay_url": "https://yaml.example/"}


def test_apply_yaml_config_lets_the_environment_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://env.example/")

    class PlatformConfig:
        extra: dict[str, Any] = {}

    merged = apply_yaml_config({"extra": {"relay_url": "https://yaml.example/"}}, PlatformConfig())
    assert merged is not None
    assert "relay_url" not in merged


def test_apply_yaml_config_tolerates_empty_input() -> None:
    class PlatformConfig:
        extra: dict[str, Any] = {}

    assert apply_yaml_config({}, PlatformConfig()) == {}
