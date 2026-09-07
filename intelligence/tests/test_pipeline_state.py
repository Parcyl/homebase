"""Tests for pipeline state contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import pipeline_state


def test_read_returns_defaults_when_missing(isolated_homebase: Path):
    state = pipeline_state.read(isolated_homebase)
    assert state["stage"] == "idle"
    assert state["session_id"] is None
    assert state["error"] is None


def test_update_writes_atomically_and_preserves_fields(isolated_homebase: Path):
    pipeline_state.update("recording", "2026-05-25T10-00-00-test", homebase_root=isolated_homebase)
    pipeline_state.update("classifying", homebase_root=isolated_homebase)

    path = isolated_homebase / "agents" / "pipeline-state.json"
    payload = json.loads(path.read_text())
    assert payload["stage"] == "classifying"
    assert payload["session_id"] == "2026-05-25T10-00-00-test"
    assert payload["started_at"] is not None  # from the recording stage


def test_update_complete_records_outputs(isolated_homebase: Path):
    pipeline_state.update(
        "complete",
        "2026-05-25T10-00-00-test",
        homebase_root=isolated_homebase,
        last_prd="prds/2026-05-25T10-00-00-test/PRD.md",
        last_handoff="prds/2026-05-25T10-00-00-test/handoff-prompt.md",
    )
    state = pipeline_state.read(isolated_homebase)
    assert state["stage"] == "complete"
    assert state["last_prd"] == "prds/2026-05-25T10-00-00-test/PRD.md"
    assert state["last_handoff"] == "prds/2026-05-25T10-00-00-test/handoff-prompt.md"


def test_update_error_stage_holds_message(isolated_homebase: Path):
    pipeline_state.update(
        "error",
        "2026-05-25T10-00-00-test",
        homebase_root=isolated_homebase,
        error="LLM 500",
    )
    state = pipeline_state.read(isolated_homebase)
    assert state["stage"] == "error"
    assert state["error"] == "LLM 500"


def test_invalid_stage_rejected(isolated_homebase: Path):
    with pytest.raises(ValueError):
        pipeline_state.update("done", homebase_root=isolated_homebase)


def test_read_tolerates_malformed_json(isolated_homebase: Path):
    path = isolated_homebase / "agents" / "pipeline-state.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text("{ not json")
    state = pipeline_state.read(isolated_homebase)
    assert state["stage"] == "idle"
