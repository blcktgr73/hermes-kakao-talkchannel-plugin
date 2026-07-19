"""KakaoTalk Channel platform adapter for Hermes Agent."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"


def register(ctx: Any) -> None:
    """Plugin entry point — called by the Hermes plugin system at startup.

    Imports stay inside the function body: the platform registry loads adapter
    modules lazily so heavy SDK imports don't slow down every ``hermes``
    invocation (docs/00-hermes-plugin-sdk.md §4).
    """
    from .registration import register_platform

    register_platform(ctx)


__all__ = ["__version__", "register"]
