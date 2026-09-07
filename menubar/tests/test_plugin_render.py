"""Tests for the SwiftBar plugin renderer.

We import the script as a module via importlib so we can call render() directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from lib.state import StateView

_PLUGIN_PATH = Path(__file__).resolve().parents[1] / "homebase_status.10s.py"
_spec = importlib.util.spec_from_file_location("homebase_status", _PLUGIN_PATH)
plugin = importlib.util.module_from_spec(_spec)
sys.modules["homebase_status"] = plugin
assert _spec.loader is not None
_spec.loader.exec_module(plugin)


def _render(stage: str = "idle", healthy: bool = True, **kwargs) -> str:
    state = StateView(stage=stage, **kwargs)
    return plugin.render(state, healthy=healthy, log_lines=[])


def test_idle_renders_green(fake_homebase):
    out = _render("idle", healthy=True)
    assert out.startswith("● Homebase")
    assert "color=#1DAF29" in out.splitlines()[0]
    assert "Stage: Idle" in out


def test_processing_renders_yellow(fake_homebase):
    out = _render("classifying", healthy=True, session_id="2026-05-25T10-00-00-x")
    assert "color=#E8B900" in out.splitlines()[0]
    assert "Stage: Classifying" in out
    assert "Session: 2026-05-25T10-00-00-x" in out


def test_grounding_stage_renders_processing(fake_homebase):
    out = _render("grounding", healthy=True)
    assert "color=#E8B900" in out.splitlines()[0]
    assert "Stage: Grounding" in out


def test_error_stage_renders_red(fake_homebase):
    out = _render("error", healthy=True, error="boom")
    assert "color=#D33333" in out.splitlines()[0]
    assert "Error: boom" in out


def test_health_down_renders_red_even_when_idle(fake_homebase):
    out = _render("idle", healthy=False)
    assert "color=#D33333" in out.splitlines()[0]
    assert "Intelligence: down" in out


def test_unknown_state_shows_hint(fake_homebase):
    state = StateView(stage="unknown", readable=False)
    out = plugin.render(state, healthy=True, log_lines=[])
    assert "State file unreadable" in out


def test_dropdown_contains_all_actions(fake_homebase):
    out = _render("idle", healthy=True)
    for action in (
        "Start Session",
        "Copy Handoff Prompt",
        "Open Last PRD",
        "Open Last Digest",
        "Open Inbox",
        "Tail Logs",
        "Restart Services",
    ):
        assert action in out, f"missing action: {action}"


def test_recording_stage_shows_stop_not_start(fake_homebase):
    out = _render("recording", healthy=True, session_id="x")
    assert "Stop Session" in out
    assert "● Start Session" not in out


def test_capture_alert_turns_title_red(fake_homebase, monkeypatch):
    session = fake_homebase / "recordings" / "2026-05-25T10-00-00-x"
    session.mkdir(parents=True)
    (session / ".capture-alert").write_text("provider frozen\n", encoding="utf-8")
    out = _render("recording", healthy=True, session_id="2026-05-25T10-00-00-x")
    assert "color=#D33333" in out.splitlines()[0]
    assert "CAPTURE FAILED: provider frozen" in out


def test_log_lines_render_in_dropdown(fake_homebase):
    state = StateView(stage="idle")
    out = plugin.render(
        state,
        healthy=True,
        log_lines=["- [2026-05-25T10:00:00Z] [T01] [file] [s1] [ok] one"],
    )
    assert "[T01]" in out
    assert "Recent activity" in out


def test_pipes_in_log_are_sanitized(fake_homebase):
    state = StateView(stage="idle")
    out = plugin.render(state, healthy=True, log_lines=["line | with | pipes"])
    # SwiftBar uses | as separator; we replace
    lines_after_recent = out.split("Recent activity", 1)[1]
    # The pipe in the message text should be sanitized to /
    assert "line / with / pipes" in lines_after_recent
