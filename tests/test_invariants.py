"""Structural invariants from docs/01-architecture.md §7.

These guard the properties that make the plugin portable and keep Hermes CLI
startup fast — both are easy to break accidentally during a refactor.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "hermes_kakao_talkchannel"
REPO_ROOT = Path(__file__).resolve().parent.parent

_HOST_MODULE_PREFIXES = ("hermes", "gateway", "hermes_agent")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


@pytest.mark.parametrize(
    "source_file", sorted((PACKAGE_ROOT / "kakao").glob("*.py")), ids=lambda p: p.name
)
def test_kakao_package_never_imports_the_host(source_file: Path) -> None:
    """INVARIANT 1: the pure domain layer stays host-agnostic."""
    offending = {
        module
        for module in _imported_modules(source_file)
        if module.split(".")[0] in _HOST_MODULE_PREFIXES
    }
    assert not offending, f"{source_file.name} imports host module(s): {sorted(offending)}"


def test_register_does_not_import_heavy_modules_at_package_scope() -> None:
    """INVARIANT 2: the registry loads platform modules lazily; keep startup cheap."""
    init_file = PACKAGE_ROOT / "__init__.py"
    top_level = _imported_modules(init_file)
    assert "aiohttp" not in top_level
    assert not any(module.startswith("hermes_kakao_talkchannel") for module in top_level)


def test_plugin_manifest_declares_the_platform_kind() -> None:
    """INVARIANT 3: an unrecognized `kind` silently degrades to `standalone`."""
    manifest = yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == "platform"
    assert manifest["name"] == "kakao-talkchannel"
    assert manifest["label"] == "KakaoTalk"


def test_manifest_version_matches_the_package_version() -> None:
    from hermes_kakao_talkchannel import __version__

    manifest = yaml.safe_load((REPO_ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert str(manifest["version"]) == __version__


def test_registration_only_passes_known_platform_entry_fields() -> None:
    """INVARIANT 4: unknown kwargs raise TypeError from PlatformEntry."""
    known_fields = {
        "name",
        "label",
        "adapter_factory",
        "check_fn",
        "validate_config",
        "required_env",
        "install_hint",
        # PlatformEntry fields forwarded via **entry_kwargs
        "is_connected",
        "setup_fn",
        "plugin_name",
        "allowed_users_env",
        "allow_all_env",
        "max_message_length",
        "pii_safe",
        "emoji",
        "allow_update_command",
        "platform_hint",
        "env_enablement_fn",
        "apply_yaml_config_fn",
        "cron_deliver_env_var",
        "standalone_sender_fn",
    }

    source = (PACKAGE_ROOT / "registration.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "register_platform"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ctx"
    ]
    assert len(calls) == 1, "expected exactly one ctx.register_platform call"

    passed = {keyword.arg for keyword in calls[0].keywords if keyword.arg}
    unknown = passed - known_fields
    assert not unknown, f"unknown PlatformEntry field(s): {sorted(unknown)}"
