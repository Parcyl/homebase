"""Tests for the compare node. Deterministic, no LLM."""

from __future__ import annotations

from pathlib import Path

from app.models import Classification, Extraction
from app.nodes.compare import compare_node
from app.state import PipelineState


def _state(classification: Classification, tools: list[str]) -> PipelineState:
    extraction = Extraction(operator_intent="t", tools_observed=tools)
    return {
        "session_id": "2026-05-25T10-00-00-test",
        "recording_path": "/tmp/raw.mp4",
        "transcript": "x",
        "keyframe_paths": [],
        "classification": classification,
        "extraction": extraction,
    }


def test_new_pattern_when_library_empty(isolated_homebase: Path):
    cls = Classification(
        deal_type="self storage",
        sub_type="acquisition",
        operator_intent_slug="round-rock-pad-count",
        confidence=0.9,
        rationale="Operator said self storage three times.",
    )
    out = compare_node(_state(cls, ["snowflake", "google-maps"]))
    cmp = out["comparison"]
    assert cmp.match == "new"
    assert cmp.target_library_path == "workflows/library/self-storage/acquisition/round-rock-pad-count"
    assert cmp.extends is None


def test_extends_when_exact_path_exists(isolated_homebase: Path):
    existing = (
        isolated_homebase
        / "workflows"
        / "library"
        / "self-storage"
        / "acquisition"
        / "round-rock-pad-count"
    )
    existing.mkdir(parents=True)
    (existing / "pattern.md").write_text("# pattern\n", encoding="utf-8")

    cls = Classification(
        deal_type="self storage",
        sub_type="acquisition",
        operator_intent_slug="round-rock-pad-count",
        confidence=0.9,
        rationale="x",
    )
    out = compare_node(_state(cls, ["snowflake"]))
    cmp = out["comparison"]
    assert cmp.match == "extends"
    assert cmp.extends == "workflows/library/self-storage/acquisition/round-rock-pad-count"


def test_extends_when_tool_overlap_high(isolated_homebase: Path):
    existing = (
        isolated_homebase
        / "workflows"
        / "library"
        / "self-storage"
        / "acquisition"
        / "different-slug"
    )
    existing.mkdir(parents=True)
    (existing / "pattern.md").write_text(
        "# pattern\n\n## Tools commonly used\n- Snowflake\n- Google Maps\n- ArcGIS\n",
        encoding="utf-8",
    )

    cls = Classification(
        deal_type="self storage",
        sub_type="acquisition",
        operator_intent_slug="new-slug",
        confidence=0.9,
        rationale="x",
    )
    # 3 of 4 tools overlap, Jaccard = 3/4 = 0.75 ≥ 0.6
    out = compare_node(_state(cls, ["Snowflake", "Google Maps", "ArcGIS", "CoStar"]))
    cmp = out["comparison"]
    assert cmp.match == "extends"
    assert "different-slug" in cmp.extends
