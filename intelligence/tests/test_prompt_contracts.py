"""Prompt-contract tests (PRD rework Story 2).

The extract/generate prompts are the quality lever. These tests pin the
contract: the guard language is present, the fabrication-driving agent
taxonomy is gone, and both prompts still render through str.format() with the
kwargs the nodes pass (a stray literal brace would raise KeyError/ValueError).
"""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).parent.parent / "app" / "prompts"


def _read(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


# ── extract.md ────────────────────────────────────────────────────────────────


def test_extract_prompt_requests_components_and_categories():
    text = _read("extract.md")
    assert "components" in text
    for cat in ("ui_ux", "data_integration", "codifiable_logic", "ai_intelligence", "open_question"):
        assert cat in text, f"category {cat} missing from extract prompt"


def test_extract_prompt_has_judgment_and_grounding_guards():
    text = _read("extract.md")
    assert "operator_judgments" in text
    assert "v1_fallback" in text
    assert "phase2_approach" in text
    assert "to_investigate" in text or "to investigate" in text
    # acceptance criteria must demand a threshold
    assert "threshold" in text


def test_extract_prompt_drops_fictional_agent_taxonomy():
    text = _read("extract.md")
    # The old prompt told the model to assign Dispatch/Parcel/Plat/Basis agents,
    # which drove fabricated workflow (HF3). That instruction must be gone.
    assert "Dispatch, Parcel, Plat" not in text
    assert "candidate agent name" not in text


def test_extract_prompt_still_renders():
    text = _read("extract.md")
    rendered = text.format(keyframe_paths="(none)", transcript="hello operator")
    assert "hello operator" in rendered


# ── generate.md ───────────────────────────────────────────────────────────────


def test_generate_prompt_states_three_hard_fail_guards():
    text = _read("generate.md").lower()
    assert "do not fabricate what exists" in text
    assert "do not spec judgment as trivial" in text
    assert "do not invent workflow" in text


def test_generate_prompt_forces_to_investigate_when_ungrounded():
    text = _read("generate.md")
    assert "to investigate" in text
    assert "target_repo" in text


def test_generate_prompt_carries_contracts_and_thresholds():
    text = _read("generate.md").lower()
    assert "data contract" in text
    assert "threshold" in text
    assert "scope" in text


def test_generate_prompt_still_renders():
    text = _read("generate.md")
    rendered = text.format(
        workflow_map_template="WM",
        prd_template="PRD",
        handoff_template="HANDOFF",
        session_id="2026-06-01T17-05-00-deal",
        recording_path="recordings/x/raw.mp4",
        classification_json="{}",
        extraction_json="{}",
        comparison_json="{}",
        library_path="workflows/library/x",
    )
    assert "HANDOFF" in rendered
    assert "2026-06-01T17-05-00-deal" in rendered
