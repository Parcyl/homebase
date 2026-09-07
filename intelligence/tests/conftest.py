"""Shared test fixtures. Every test runs against an isolated HOMEBASE_ROOT."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def isolated_homebase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fresh repo skeleton in a tmp dir, with HOMEBASE_ROOT pointed at it."""
    for sub in (
        "recordings",
        "prds",
        "memory",
        "workflows/library",
        "templates",
        "inbox",
    ):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    # Minimal seed templates so generate_node has something to read
    (tmp_path / "templates" / "workflow-map-template.md").write_text("# Workflow Map template\n", encoding="utf-8")
    (tmp_path / "templates" / "PRD-template.md").write_text("# PRD template\n", encoding="utf-8")
    (tmp_path / "templates" / "handoff-template.md").write_text("# Handoff template\n", encoding="utf-8")
    (tmp_path / "memory" / "patterns.md").write_text("# Patterns\n", encoding="utf-8")
    (tmp_path / "workflows" / "library" / ".gitkeep").write_text("", encoding="utf-8")

    monkeypatch.setenv("HOMEBASE_ROOT", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Bust the cached settings so the env override takes effect
    from app import settings as settings_module

    settings_module.get_settings.cache_clear()
    yield tmp_path
    settings_module.get_settings.cache_clear()
    os.environ.pop("HOMEBASE_ROOT", None)
