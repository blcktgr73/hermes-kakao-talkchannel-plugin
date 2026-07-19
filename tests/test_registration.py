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
    """Stand-in for Hermes' PluginContext, capturing the registration call."""

    def __init__(self) -> None:
        self.platforms: list[dict[str, Any]] = []

    def register_platform(self, **kwargs: Any) -> None:
        self.platforms.append(kwargs)


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


def test_is_connected_without_an_adapter() -> None:
    assert is_connected(None) is False


def test_is_connected_reflects_adapter_state() -> None:
    class Adapter:
        _connected = True

    assert is_connected(Adapter()) is True


def test_validate_config_returns_no_errors_for_defaults() -> None:
    class Cfg:
        extra: dict[str, Any] = {}

    assert validate_config(Cfg()) == []


def test_validate_config_surfaces_range_errors() -> None:
    class Cfg:
        extra = {"text_chunk_limit": 5}

    errors = validate_config(Cfg())
    assert any("text_chunk_limit" in error for error in errors)


def test_env_enablement_seeds_extra_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAKAO_RELAY_URL", "https://env-relay.example/")
    monkeypatch.setenv("KAKAO_RESPONSE_PREFIX", "[봇] ")

    extra = env_enablement()

    assert extra is not None
    assert extra["relay_url"] == "https://env-relay.example/"
    assert extra["response_prefix"] == "[봇] "


def test_env_enablement_omits_absent_optional_keys() -> None:
    extra = env_enablement()
    assert extra is not None
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
