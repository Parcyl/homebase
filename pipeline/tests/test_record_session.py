"""Tests for record_session (Start/Stop markers + stop-time narration capture via the
TranscriptProvider seam). Ported from the original agents/scripts/test_record_session.py;
Vowen-specific window-selection coverage now lives in providers/transcript/tests/test_vowen.py,
these tests exercise record_session.py's own logic (session bookkeeping, build_transcript,
provider wiring) with an injected VowenProvider standing in for "some provider or other".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import record_session as rs
from providers.transcript.provider import TranscriptEntry
from providers.transcript.vowen import VowenProvider


@pytest.fixture
def fake_homebase(tmp_path: Path) -> Path:
    for sub in ("recordings", "agents"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _write_vowen(path: Path, entries: list[dict]) -> Path:
    """Vowen-shaped history: newest-first list of {timestamp, text}."""
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def _vowen_provider(history_path: Path) -> VowenProvider:
    return VowenProvider(history_path=history_path)


# --- session id + start -----------------------------------------------------

def test_make_session_id_is_date_first_and_slugged():
    now = datetime(2026, 6, 1, 20, 30, 15, tzinfo=UTC)
    assert rs.make_session_id(now) == "2026-06-01T20-30-15"
    assert rs.make_session_id(now, slug="Hunt County!") == "2026-06-01T20-30-15-hunt-county"


def test_start_session_creates_dir_and_marker(fake_homebase: Path):
    now = datetime(2026, 6, 1, 20, 30, 15, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=now, slug="deal")
    assert sid == "2026-06-01T20-30-15-deal"
    assert (fake_homebase / "recordings" / sid).is_dir()
    marker = json.loads((fake_homebase / "agents" / ".rec-session.json").read_text())
    assert marker["session_id"] == sid
    assert marker["start_epoch"] == now.timestamp()


# --- build_transcript (provider-agnostic) ------------------------------------

def test_build_transcript_concatenates():
    entries = [
        TranscriptEntry(epoch=1.0, ts_iso="2026-06-01T20:31:00Z", text="first part", source="vowen"),
        TranscriptEntry(epoch=2.0, ts_iso="2026-06-01T20:33:00Z", text="second part", source="vowen"),
    ]
    t = rs.build_transcript(entries)
    assert t is not None
    assert t["source"] == "vowen"
    assert t["entry_count"] == 2
    assert "first part" in t["text"] and "second part" in t["text"]
    assert t["text"].index("first part") < t["text"].index("second part")


def test_build_transcript_none_when_empty():
    assert rs.build_transcript([]) is None


def test_build_transcript_source_reflects_whichever_provider_supplied_entries():
    entries = [TranscriptEntry(epoch=1.0, ts_iso="", text="hi", source="file")]
    assert rs.build_transcript(entries)["source"] == "file"


# --- stop -------------------------------------------------------------------

def test_stop_session_writes_transcript_and_clears_marker(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": "2026-06-01T20:40:00Z", "text": "the whole narration"},
    ])
    result = rs.stop_session(fake_homebase, provider=_vowen_provider(hist))

    assert result["session_id"] == sid
    assert result["entry_count"] == 1
    transcript_path = fake_homebase / "recordings" / sid / "transcript.json"
    assert transcript_path.exists()
    saved = json.loads(transcript_path.read_text())
    assert saved["text"] == "the whole narration"
    assert saved["source"] == "vowen"
    # marker cleared so a second stop is a no-op
    assert not (fake_homebase / "agents" / ".rec-session.json").exists()


def test_stop_session_no_active_marker_raises(fake_homebase: Path):
    with pytest.raises(rs.NoActiveSession):
        rs.stop_session(fake_homebase, provider=_vowen_provider(fake_homebase / "vowen.json"))


def test_stop_session_no_vowen_entries_writes_nothing(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": "2026-06-01T20:00:00Z", "text": "before start"},
    ])
    result = rs.stop_session(fake_homebase, provider=_vowen_provider(hist))
    assert result["entry_count"] == 0
    # No transcript written (watcher will fall back or report no-transcript)
    assert not (fake_homebase / "recordings" / sid / "transcript.json").exists()
    # marker still cleared
    assert not (fake_homebase / "agents" / ".rec-session.json").exists()


def test_stop_session_defaults_to_configured_provider(fake_homebase: Path, monkeypatch):
    """No provider passed -> get_provider(DICTATION_PROVIDER) is used."""
    monkeypatch.setenv("DICTATION_PROVIDER", "file")
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    session_dir = fake_homebase / "recordings" / sid
    (session_dir / "transcript.json").write_text(
        json.dumps([{"epoch": start.timestamp() + 60, "text": "dropped by the operator"}]),
        encoding="utf-8",
    )
    result = rs.stop_session(fake_homebase)  # no provider kwarg at all
    assert result["entry_count"] == 1
    saved = json.loads((session_dir / "transcript.json").read_text())
    assert saved["source"] == "file"


# --- session.json bounds + deferred capture ----------------------------------

def _meta(homebase: Path, sid: str) -> dict:
    return json.loads((homebase / "recordings" / sid / "session.json").read_text())


def test_start_session_writes_session_meta(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    meta = _meta(fake_homebase, sid)
    assert meta["session_id"] == sid
    assert meta["start_epoch"] == start.timestamp()


def test_stop_session_records_stop_epoch_and_defers(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 21, 5, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    # Vowen has NOT flushed the narration yet at stop time (only an out-of-window entry).
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": "2026-06-01T19:00:00Z", "text": "yesterday"},
    ])
    result = rs.stop_session(fake_homebase, provider=_vowen_provider(hist), now=stop)
    assert result["entry_count"] == 0
    assert result["deferred"] is True
    meta = _meta(fake_homebase, sid)
    assert meta["stop_epoch"] == stop.timestamp()


def test_capture_session_writes_transcript_from_window(fake_homebase: Path):
    """The deferred path: stop captured nothing; the flush appears later; capture gets it."""
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 21, 5, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    empty = _write_vowen(fake_homebase / "vowen.json", [])
    rs.stop_session(fake_homebase, provider=_vowen_provider(empty), now=stop)
    assert not (fake_homebase / "recordings" / sid / "transcript.json").exists()

    # Vowen flushes the narration 60s after stop.
    flushed = datetime(2026, 6, 1, 21, 6, 0, tzinfo=UTC)
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": flushed.isoformat(), "text": "narration that flushed late"},
    ])
    result = rs.capture_session(fake_homebase, sid, provider=_vowen_provider(hist))
    assert result["entry_count"] == 1
    saved = json.loads((fake_homebase / "recordings" / sid / "transcript.json").read_text())
    assert saved["text"] == "narration that flushed late"
    assert saved["source"] == "vowen"


def test_capture_session_idempotent_when_transcript_exists(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=start, slug="deal")
    tpath = fake_homebase / "recordings" / sid / "transcript.json"
    tpath.write_text(json.dumps({"text": "already here", "source": "vowen"}), encoding="utf-8")
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": "2026-06-01T20:40:00Z", "text": "should not overwrite"},
    ])
    result = rs.capture_session(fake_homebase, sid, provider=_vowen_provider(hist))
    assert result.get("skipped") is True
    assert json.loads(tpath.read_text())["text"] == "already here"


def test_capture_session_missing_meta_returns_error(fake_homebase: Path):
    (fake_homebase / "recordings" / "no-meta").mkdir(parents=True, exist_ok=True)
    hist = _write_vowen(fake_homebase / "vowen.json", [])
    result = rs.capture_session(fake_homebase, "no-meta", provider=_vowen_provider(hist))
    assert result["entry_count"] == 0
    assert "error" in result


# --- sessions-dir isolation (a second, independent capture flow) ------------

def test_start_session_alt_dir_uses_own_folder_and_marker(fake_homebase: Path):
    now = datetime(2026, 6, 1, 20, 30, 15, tzinfo=UTC)
    sid = rs.start_session(fake_homebase, now=now, slug="bugs", sessions_dir="bugs-mvp/sessions")
    # Lands under the alt sessions dir, NOT recordings/ (the default watcher never sees it).
    assert (fake_homebase / "bugs-mvp/sessions" / sid).is_dir()
    assert not (fake_homebase / "recordings" / sid).exists()
    # Default marker is untouched; the alt flow gets its own marker.
    assert not (fake_homebase / "agents" / ".rec-session.json").exists()
    marker = json.loads((fake_homebase / "agents" / ".rec-session-bugs-mvp-sessions.json").read_text())
    assert marker["session_id"] == sid
    assert marker["sessions_dir"] == "bugs-mvp/sessions"


def test_alt_dir_session_does_not_collide_with_default_session(fake_homebase: Path):
    now = datetime(2026, 6, 1, 20, 30, 15, tzinfo=UTC)
    deal = rs.start_session(fake_homebase, now=now, slug="deal")
    alt = rs.start_session(fake_homebase, now=now, slug="bugs", sessions_dir="bugs-mvp/sessions")
    # Two live sessions, two separate markers -- neither clobbers the other.
    deal_marker = json.loads((fake_homebase / "agents" / ".rec-session.json").read_text())
    alt_marker = json.loads(
        (fake_homebase / "agents" / ".rec-session-bugs-mvp-sessions.json").read_text()
    )
    assert deal_marker["session_id"] == deal
    assert alt_marker["session_id"] == alt


def test_stop_and_capture_roundtrip_in_alt_dir(fake_homebase: Path):
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 20, 35, 0, tzinfo=UTC)
    sd = "bugs-mvp/sessions"
    sid = rs.start_session(fake_homebase, now=start, slug="bugs", sessions_dir=sd)
    hist = _write_vowen(fake_homebase / "vowen.json", [
        {"timestamp": "2026-06-01T20:36:00Z", "text": "the notebook panel will not scroll"},
    ])
    result = rs.stop_session(fake_homebase, provider=_vowen_provider(hist), now=stop, sessions_dir=sd)
    # Narration flushed inside the grace window -> captured at stop, in the alt dir.
    saved = json.loads((fake_homebase / sd / sid / "transcript.json").read_text())
    assert "notebook panel" in saved["text"]
    assert result["session_id"] == sid
    # Marker cleared for the alt flow.
    assert not (fake_homebase / "agents" / ".rec-session-bugs-mvp-sessions.json").exists()
