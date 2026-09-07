"""Tests for FileProvider: the bring-your-own default. Fixture files use the documented
`[{"epoch"|"ts", "text"}, ...]` schema (see providers/transcript/file.py)."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from providers.transcript.file import FileProvider


def _write(session_dir: Path, entries: list[dict]) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "transcript.json").write_text(json.dumps(entries), encoding="utf-8")


def test_entries_within_window_by_epoch(tmp_path: Path):
    _write(tmp_path, [
        {"epoch": 1000.0, "text": "before window"},
        {"epoch": 1050.0, "text": "in window"},
        {"epoch": 2000.0, "text": "after window"},
    ])
    provider = FileProvider(session_dir=tmp_path)
    entries = provider.entries_in_window(1040.0, 1060.0, tolerance_s=0, grace_s=0)
    assert [e.text for e in entries] == ["in window"]


def test_entries_within_window_by_ts(tmp_path: Path):
    _write(tmp_path, [
        {"ts": "2026-06-01T20:00:00Z", "text": "before"},
        {"ts": "2026-06-01T20:31:00Z", "text": "during"},
    ])
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 20, 35, 0, tzinfo=UTC)
    provider = FileProvider(session_dir=tmp_path)
    entries = provider.entries_in_window(start.timestamp(), stop.timestamp())
    assert [e.text for e in entries] == ["during"]


def test_entry_without_timestamp_is_always_included(tmp_path: Path):
    """Zero tool assumptions: an untimed entry can't be windowed, so it's trusted."""
    _write(tmp_path, [{"text": "no timestamp at all"}])
    provider = FileProvider(session_dir=tmp_path)
    entries = provider.entries_in_window(9_999_999_999.0, 9_999_999_999.0)
    assert [e.text for e in entries] == ["no timestamp at all"]


def test_blank_text_entries_are_dropped(tmp_path: Path):
    _write(tmp_path, [{"epoch": 1000.0, "text": "   "}, {"epoch": 1000.0, "text": "real"}])
    provider = FileProvider(session_dir=tmp_path)
    entries = provider.entries_in_window(900.0, 1100.0)
    assert [e.text for e in entries] == ["real"]


def test_missing_file_returns_empty(tmp_path: Path):
    provider = FileProvider(session_dir=tmp_path)  # no transcript.json written
    assert provider.entries_in_window(0.0, None) == []


def test_no_session_dir_returns_empty():
    provider = FileProvider()
    assert provider.entries_in_window(0.0, None) == []


def test_source_is_file():
    from providers.transcript.file import FileProvider as FP
    assert FP.name == "file"


def test_health_is_always_healthy(tmp_path: Path):
    provider = FileProvider(session_dir=tmp_path)
    health = provider.health()
    assert health.healthy is True
    assert health.running is None
