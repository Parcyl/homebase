"""Test fixtures for menu bar plugin tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_MENU_BAR = Path(__file__).resolve().parents[1]
if str(_MENU_BAR) not in sys.path:
    sys.path.insert(0, str(_MENU_BAR))


@pytest.fixture
def fake_homebase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for sub in ("agents", "prds", "recordings", "inbox", "workflows/library"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOMEBASE_ROOT", str(tmp_path))
    return tmp_path
