"""Drop-in shim for ``~/.hermes/plugins/kakao-talkchannel/``.

Hermes discovers this plugin two ways (docs/00-hermes-plugin-sdk.md §7):

1. pip install + the ``hermes_agent.plugins`` entry point, which resolves
   straight to the ``hermes_kakao_talkchannel`` package.
2. Cloning this repository into ``~/.hermes/plugins/<name>/``, where the
   directory *itself* is the plugin and this file is its entry point.

In case 2 the inner package is not importable unless its parent directory is on
``sys.path``, so add it before re-exporting ``register``.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from hermes_kakao_talkchannel import register  # noqa: E402

__all__ = ["register"]
