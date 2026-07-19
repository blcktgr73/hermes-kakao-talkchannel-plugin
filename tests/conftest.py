from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_KAKAO_ENV_PREFIX = "KAKAO_"
_OTHER_ENV = ("OPENCLAW_TALKCHANNEL_RELAY_TOKEN", "HERMES_HOME")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's real KakaoTalk/Hermes env out of every test."""
    for name in list(os.environ):
        if name.startswith(_KAKAO_ENV_PREFIX):
            monkeypatch.delenv(name, raising=False)
    for name in _OTHER_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the session store at a throwaway HERMES_HOME."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path
