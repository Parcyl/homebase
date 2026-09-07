"""Tests for WisprFlowProvider: best-effort, unverified schema (see module docstring in
providers/transcript/wisprflow.py for what was and wasn't confirmed)."""
from __future__ import annotations

import json
from pathlib import Path

from providers.transcript.wisprflow import WisprFlowProvider


def _write(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_unconfigured_provider_has_no_entries_and_reports_soft_issue(tmp_path: Path):
    provider = WisprFlowProvider(history_path=None)
    assert provider.entries_in_window(0.0, 100.0) == []
    health = provider.health()
    assert health.healthy is True  # never hard-blocks; it's unverified, not broken
    assert any(i.name == "wisprflow_history_configured" and not i.passed for i in health.issues)


def test_reads_vowen_shaped_entries(tmp_path: Path):
    hist = _write(tmp_path / "wispr.json", [
        {"timestamp": "2026-06-01T20:31:00Z", "text": "vowen-shaped"},
    ])
    provider = WisprFlowProvider(history_path=hist)
    entries = provider.entries_in_window(0.0, None)
    assert [e.text for e in entries] == ["vowen-shaped"]
    assert entries[0].source == "wisprflow"


def test_reads_file_shaped_entries(tmp_path: Path):
    hist = _write(tmp_path / "wispr.json", [
        {"epoch": 1000.0, "text": "file-shaped"},
    ])
    provider = WisprFlowProvider(history_path=hist)
    entries = provider.entries_in_window(900.0, 1100.0)
    assert [e.text for e in entries] == ["file-shaped"]


def test_unwraps_history_key(tmp_path: Path):
    hist = _write(tmp_path / "wispr.json", {"history": [
        {"timestamp": "2026-06-01T20:31:00Z", "text": "wrapped"},
    ]})
    provider = WisprFlowProvider(history_path=hist)
    entries = provider.entries_in_window(0.0, None)
    assert [e.text for e in entries] == ["wrapped"]


def test_entry_with_no_recognizable_timestamp_is_dropped_not_trusted(tmp_path: Path):
    """Unlike FileProvider, an unconfirmed schema gets no benefit of the doubt."""
    hist = _write(tmp_path / "wispr.json", [{"text": "no timestamp"}])
    provider = WisprFlowProvider(history_path=hist)
    assert provider.entries_in_window(0.0, None) == []


def test_missing_file_returns_empty(tmp_path: Path):
    provider = WisprFlowProvider(history_path=tmp_path / "nope.json")
    assert provider.entries_in_window(0.0, None) == []
