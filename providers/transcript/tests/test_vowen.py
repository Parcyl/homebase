"""Tests for VowenProvider (window selection + readiness checks).

Ported from the original agents/scripts/test_record_session.py (window selection) and
test_capture_guards.py (evaluate_vowen_crash / evaluate_mic), now exercised through the
adapter directly rather than through record_session.py or capture_healthcheck.py.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from providers.transcript.vowen import VowenProvider, evaluate_mic, evaluate_vowen_crash


def _write_vowen(path: Path, entries: list[dict]) -> Path:
    """Vowen-shaped history: newest-first list of {timestamp, text}."""
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


# ---------- window selection: entries_in_window(start, None) == "since start" ----------

def test_entries_since_start_collects_window_chronologically(tmp_path: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    hist = _write_vowen(tmp_path / "vowen.json", [
        # newest-first as Vowen stores it
        {"timestamp": "2026-06-01T20:35:00Z", "text": "third"},
        {"timestamp": "2026-06-01T20:33:00Z", "text": "second"},
        {"timestamp": "2026-06-01T20:31:00Z", "text": "first"},
        {"timestamp": "2026-06-01T20:00:00Z", "text": "before start, excluded"},
    ])
    provider = VowenProvider(history_path=hist)
    entries = provider.entries_in_window(start.timestamp(), None)
    texts = [e.text for e in entries]
    assert texts == ["first", "second", "third"]  # chronological, window only


def test_entries_since_start_empty_when_nothing_after_start(tmp_path: Path):
    start = datetime(2026, 6, 1, 21, 0, 0, tzinfo=UTC)
    hist = _write_vowen(tmp_path / "vowen.json", [
        {"timestamp": "2026-06-01T20:31:00Z", "text": "old"},
    ])
    provider = VowenProvider(history_path=hist)
    assert provider.entries_in_window(start.timestamp(), None) == []


def test_entries_since_start_missing_file_returns_empty(tmp_path: Path):
    provider = VowenProvider(history_path=tmp_path / "nope.json")
    assert provider.entries_in_window(0.0, None) == []


# ---------- window selection: [start, stop + grace] ----------

def test_window_includes_entry_flushed_just_after_stop(tmp_path: Path):
    """Regression: Vowen stamps the final entry at flush time, after the stop click.

    A strict upper bound would drop it if flushed shortly after stop. The grace window
    must keep it.
    """
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 21, 5, 0, tzinfo=UTC)
    flushed = datetime(2026, 6, 1, 21, 6, 0, tzinfo=UTC)  # +60s, within default grace (120s)
    hist = _write_vowen(tmp_path / "vowen.json", [
        {"timestamp": flushed.isoformat(), "text": "the whole narration"},
    ])
    provider = VowenProvider(history_path=hist)
    entries = provider.entries_in_window(start.timestamp(), stop.timestamp())
    assert len(entries) == 1
    assert entries[0].text == "the whole narration"
    assert entries[0].source == "vowen"


def test_window_excludes_entry_beyond_grace(tmp_path: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 21, 5, 0, tzinfo=UTC)
    late = datetime(2026, 6, 1, 21, 10, 0, tzinfo=UTC)  # +5min, well past 120s grace
    hist = _write_vowen(tmp_path / "vowen.json", [
        {"timestamp": late.isoformat(), "text": "unrelated later chatter"},
    ])
    provider = VowenProvider(history_path=hist)
    entries = provider.entries_in_window(start.timestamp(), stop.timestamp())
    assert entries == []


# ---------- readiness: crash-since-launch ----------

def test_crash_newer_than_process_start_blocks():
    r = evaluate_vowen_crash(proc_start=1000.0, crash_mtime=2000.0)
    assert not r.passed and r.blocking


def test_crash_older_than_process_start_passes():
    r = evaluate_vowen_crash(proc_start=2000.0, crash_mtime=1000.0)
    assert r.passed


def test_no_crash_dump_passes():
    r = evaluate_vowen_crash(proc_start=2000.0, crash_mtime=None)
    assert r.passed


def test_unknown_process_start_is_soft():
    r = evaluate_vowen_crash(proc_start=None, crash_mtime=1000.0)
    assert not r.passed and not r.blocking  # advisory, never blocks


# ---------- readiness: mic key (a prior agent used a nonexistent 'defaultMic') ----------

def test_mic_reads_real_key():
    r = evaluate_mic({"microphoneDeviceName": "Yeti Stereo Microphone"},
                     expected="Yeti Stereo Microphone")
    assert r.passed


def test_mic_mismatch_is_soft_fail():
    r = evaluate_mic({"microphoneDeviceName": "MacBook Mic"}, expected="Yeti Stereo Microphone")
    assert not r.passed and not r.blocking


def test_mic_missing_does_not_crash():
    r = evaluate_mic({}, expected="Yeti Stereo Microphone")
    assert not r.passed and not r.blocking


def test_mic_unconfigured_expectation_is_a_pass():
    r = evaluate_mic({"microphoneDeviceName": "Anything"}, expected="")
    assert r.passed


# ---------- health(): the artifact-freshness signal the liveness monitor watches ----------

def test_health_reports_not_running_when_no_process(tmp_path: Path):
    provider = VowenProvider(history_path=tmp_path / "nope.json", pgrep=lambda pattern: [])
    health = provider.health()
    assert health.running is False
    assert not health.healthy  # vowen_running is a hard check


def test_health_reports_last_entry_age(tmp_path: Path):
    hist = _write_vowen(tmp_path / "vowen.json", [
        {"timestamp": "2026-06-01T20:35:00Z", "text": "third"},
        {"timestamp": "2026-06-01T20:00:00Z", "text": "first"},
    ])
    now_epoch = datetime(2026, 6, 1, 20, 36, 0, tzinfo=UTC).timestamp()
    provider = VowenProvider(
        history_path=hist,
        crash_dir=tmp_path / "no-crashes-here",  # injected: never touch the real machine's dir
        pgrep=lambda pattern: [123],
        proc_start_epoch=lambda pid: 0.0,
        now_fn=lambda: now_epoch,
    )
    health = provider.health()
    assert health.last_entry_age_s == 60.0  # 20:36 - 20:35, the NEWEST entry, not the first


def test_health_last_entry_age_none_when_no_entries(tmp_path: Path):
    provider = VowenProvider(history_path=tmp_path / "nope.json",
                             crash_dir=tmp_path / "no-crashes-here",
                             pgrep=lambda pattern: [123], proc_start_epoch=lambda pid: 0.0)
    assert provider.health().last_entry_age_s is None
