"""Tests for the file outputs node."""

from __future__ import annotations

from pathlib import Path

from app.models import (
    Classification,
    ComparisonResult,
    Extraction,
    GeneratedArtifacts,
)
from app.nodes.file_outputs import file_outputs_node


def _state() -> dict:
    return {
        "session_id": "2026-05-25T10-00-00-test",
        "recording_path": "/tmp/raw.mp4",
        "transcript": "x",
        "keyframe_paths": [],
        "classification": Classification(
            deal_type="self storage",
            sub_type="acquisition",
            operator_intent_slug="round-rock-pad-count",
            confidence=0.91,
            rationale="x",
        ),
        "extraction": Extraction(operator_intent="t"),
        "comparison": ComparisonResult(
            match="new",
            target_library_path="workflows/library/self-storage/acquisition/round-rock-pad-count",
            extends=None,
            rationale="r",
        ),
        "generated": GeneratedArtifacts(
            workflow_map_md="# Workflow Map\n",
            prd_md="# PRD\n",
            handoff_md="# Handoff\n",
            pattern_md="# Pattern\n",
        ),
    }


def test_file_outputs_writes_all_artifacts(isolated_homebase: Path):
    result = file_outputs_node(_state())
    paths = result["output_paths"]

    assert (isolated_homebase / paths.workflow_map).read_text().startswith("# Workflow Map")
    assert (isolated_homebase / paths.prd).read_text().startswith("# PRD")
    assert (isolated_homebase / paths.handoff).read_text().startswith("# Handoff")
    assert (isolated_homebase / paths.pattern).read_text().startswith("# Pattern")


def test_file_outputs_appends_to_patterns_memory(isolated_homebase: Path):
    file_outputs_node(_state())
    memory = (isolated_homebase / "memory" / "patterns.md").read_text()
    assert "self storage/acquisition/round-rock-pad-count" in memory
    assert "First observed: 2026-05-25T10-00-00-test" in memory


def test_file_outputs_idempotent(isolated_homebase: Path):
    file_outputs_node(_state())
    file_outputs_node(_state())  # second run overwrites artifacts cleanly
    pattern_path = (
        isolated_homebase
        / "workflows"
        / "library"
        / "self-storage"
        / "acquisition"
        / "round-rock-pad-count"
        / "pattern.md"
    )
    assert pattern_path.read_text() == "# Pattern\n"
