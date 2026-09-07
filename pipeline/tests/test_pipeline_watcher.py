"""Tests for pipeline_watcher. Pure stdlib; mocks subprocess and urlopen.

Ported from the source project's agents/scripts/test_pipeline_watcher.py. The deferred-capture
test now exercises the TranscriptProvider seam (providers/transcript/) via VowenProvider
instead of a hardcoded Vowen path -- see providers/transcript/tests/test_vowen.py for the
provider's own unit coverage.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pipeline_watcher as pw


@pytest.fixture
def fake_homebase(tmp_path: Path) -> Path:
    for sub in ("recordings", "prds", "inbox", "agents", "memory", "workflows/library"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_session(homebase: Path, session_id: str, mtime_offset: float = -10.0) -> Path:
    session_dir = homebase / "recordings" / session_id
    session_dir.mkdir()
    mp4 = session_dir / "raw.mp4"
    mp4.write_bytes(b"fake mp4 content")
    new_mtime = time.time() + mtime_offset
    import os
    os.utime(mp4, (new_mtime, new_mtime))
    return session_dir


def test_update_state_atomic_and_merges(fake_homebase: Path):
    pw.update_state(fake_homebase, "recording", "2026-05-27T10-00-00-test", message="r")
    pw.update_state(fake_homebase, "transcribing")
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "transcribing"
    assert state["session_id"] == "2026-05-27T10-00-00-test"
    assert state["error"] is None


def test_find_pending_skips_fresh_mp4(fake_homebase: Path):
    # mtime is 'now' so settle gate (2s) keeps it out
    _make_session(fake_homebase, "2026-05-27T10-00-00-a", mtime_offset=-0.5)
    assert pw.find_pending_recordings(fake_homebase) == []


def test_find_pending_returns_stable_mp4(fake_homebase: Path):
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-b", mtime_offset=-10)
    assert pw.find_pending_recordings(fake_homebase) == [s]


def test_find_pending_skips_processed(fake_homebase: Path):
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-c", mtime_offset=-10)
    (s / ".processed").touch()
    assert pw.find_pending_recordings(fake_homebase) == []


def test_ensure_transcript_loads_existing(fake_homebase: Path):
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-d", mtime_offset=-10)
    (s / "transcript.json").write_text(json.dumps({"text": "hello"}))
    result = pw.ensure_transcript(s)
    assert result == {"text": "hello"}


def test_ensure_transcript_runs_deferred_provider_capture(fake_homebase: Path, monkeypatch):
    """No transcript.json at process time -> watcher shells out to record_session capture,
    which pulls the configured TranscriptProvider's window (incl. the entry flushed just
    after stop) and writes it. Regression for the Seguin deal (2026-06-09), now exercised
    through the TranscriptProvider seam instead of a hardcoded Vowen path."""
    from datetime import UTC, datetime
    s = _make_session(fake_homebase, "2026-06-01T20-30-00-deal", mtime_offset=-10)
    start = datetime(2026, 6, 1, 20, 30, 0, tzinfo=UTC)
    stop = datetime(2026, 6, 1, 21, 5, 0, tzinfo=UTC)
    (s / "session.json").write_text(json.dumps({
        "session_id": s.name, "start_epoch": start.timestamp(), "stop_epoch": stop.timestamp(),
    }))
    flushed = datetime(2026, 6, 1, 21, 6, 0, tzinfo=UTC)  # 60s after stop
    vowen_history = fake_homebase / "vowen-history.json"
    vowen_history.write_text(json.dumps([{"timestamp": flushed.isoformat(), "text": "deferred narration"}]))
    monkeypatch.setenv("DICTATION_PROVIDER", "vowen")
    monkeypatch.setenv("VOWEN_HISTORY_PATH", str(vowen_history))

    result = pw.ensure_transcript(s, python_bin=sys.executable)
    assert (s / "transcript.json").exists()
    assert result is not None
    assert "deferred narration" in json.dumps(result)


def test_ensure_transcript_falls_back_to_whisper(fake_homebase: Path):
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-e", mtime_offset=-10)

    def fake_run(cmd, **kw):
        # Pretend mlx_whisper wrote raw.json
        (s / "raw.json").write_text(json.dumps({"text": "from whisper"}))
        return MagicMock(returncode=0)

    with patch.object(pw.subprocess, "run", side_effect=fake_run):
        result = pw.ensure_transcript(s)
    assert result == {"text": "from whisper"}
    assert (s / "transcript.json").exists()
    assert not (s / "raw.json").exists()


def test_ensure_transcript_returns_none_when_whisper_fails(fake_homebase: Path):
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-f", mtime_offset=-10)
    with patch.object(pw.subprocess, "run", return_value=MagicMock(returncode=1)):
        result = pw.ensure_transcript(s)
    assert result is None


def _fake_ffprobe_ffmpeg(cmds: list, duration: bytes = b"120.0\n", probe_rc: int = 0):
    """subprocess.run double: answers ffprobe with a duration, ffmpeg by writing the jpg.

    Records every invoked command into `cmds`.
    """
    def fake_run(cmd, **kw):
        cmds.append(cmd)
        if "ffprobe" in cmd[0]:
            return MagicMock(returncode=probe_rc, stdout=duration, stderr=b"")
        # ffmpeg: emulate writing the output frame (last arg is the path)
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"jpg")
        return MagicMock(returncode=0, stdout=b"", stderr=b"")
    return fake_run


def test_extract_keyframes_seeks_bounded_frame_count(fake_homebase: Path):
    """F10: extraction must be bounded and seek-based, not fps=0.5 over the whole file.

    fps=0.5 decodes the entire video and writes ~1 frame per 2s (1,096 frames for a
    36-min recording), of which the extract node uses only 10. A 36-min recording
    must not produce thousands of frames. Seek-based extraction of a fixed number of
    evenly-spaced frames is fast, length-independent, and bounded.
    """
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-kf", mtime_offset=-10)
    mp4 = s / "raw.mp4"
    kf_dir = s / "keyframes"
    cmds: list = []

    with patch.object(pw.subprocess, "run", side_effect=_fake_ffprobe_ffmpeg(cmds)):
        frames = pw.extract_keyframes(mp4, kf_dir, count=15)

    ffmpeg_cmds = [c for c in cmds if "ffmpeg" in c[0]]
    assert len(ffmpeg_cmds) == 15, f"expected 15 bounded extractions, got {len(ffmpeg_cmds)}"
    assert len(frames) == 15, "should return exactly the frames produced"
    for c in ffmpeg_cmds:
        assert "-ss" in c, f"each extraction must fast-seek: {' '.join(c)}"
        assert "-frames:v" in " ".join(c), "each extraction grabs a single frame"
    joined = " ".join(" ".join(c) for c in ffmpeg_cmds)
    assert "fps=0.5" not in joined, "the unbounded fps=0.5 approach must be gone"


def test_extract_keyframes_falls_back_when_duration_unknown(fake_homebase: Path):
    """If ffprobe can't read the duration, extraction degrades to a single frame, not a crash."""
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-nodur", mtime_offset=-10)
    mp4 = s / "raw.mp4"
    kf_dir = s / "keyframes"
    cmds: list = []

    # probe returns non-zero / empty duration
    fake = _fake_ffprobe_ffmpeg(cmds, duration=b"", probe_rc=1)
    with patch.object(pw.subprocess, "run", side_effect=fake):
        frames = pw.extract_keyframes(mp4, kf_dir, count=15)

    ffmpeg_cmds = [c for c in cmds if "ffmpeg" in c[0]]
    assert len(ffmpeg_cmds) == 1, "duration-unknown should fall back to one frame"
    assert len(frames) == 1


def test_extract_keyframes_never_raises_on_ffmpeg_failure(fake_homebase: Path):
    """Best-effort contract preserved: a failing ffmpeg must not raise."""
    s = _make_session(fake_homebase, "2026-05-27T10-00-00-kffail", mtime_offset=-10)
    mp4 = s / "raw.mp4"
    kf_dir = s / "keyframes"

    def boom(cmd, **kw):
        if "ffprobe" in cmd[0]:
            return MagicMock(returncode=0, stdout=b"60.0\n", stderr=b"")
        raise OSError("ffmpeg exploded")

    with patch.object(pw.subprocess, "run", side_effect=boom):
        frames = pw.extract_keyframes(mp4, kf_dir, count=5)
    assert frames == []  # no frames, but no exception


def _http_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda self: self
    resp.__exit__ = lambda *a: None
    return resp


def test_process_session_happy_path(fake_homebase: Path):
    sid = "2026-05-27T10-00-00-happy"
    s = _make_session(fake_homebase, sid, mtime_offset=-10)
    (s / "transcript.json").write_text(json.dumps({"text": "ok"}))

    # Pre-create the output files the intelligence spine would normally write
    prd_path = fake_homebase / "prds" / sid / "PRD.md"
    prd_path.parent.mkdir(parents=True)
    prd_path.write_text("# PRD")
    (fake_homebase / "prds" / sid / "handoff-prompt.md").write_text("# Handoff")
    wfm_path = fake_homebase / "recordings" / sid / "workflow-map.md"
    wfm_path.write_text("# WFM")
    pattern_path = fake_homebase / "workflows" / "library" / "test" / "pattern.md"
    pattern_path.parent.mkdir(parents=True)
    pattern_path.write_text("# Pattern")

    fake_response = {
        "session_id": sid,
        "classification": {"deal_type": "test", "sub_type": "x"},
        "library_path": "workflows/library/test",
        "outputs": {
            "workflow_map": f"recordings/{sid}/workflow-map.md",
            "prd": f"prds/{sid}/PRD.md",
            "handoff": f"prds/{sid}/handoff-prompt.md",
            "pattern": "workflows/library/test/pattern.md",
        },
        "pattern_match": {"match": "new"},
        "low_confidence": False,
    }

    with patch.object(pw, "extract_keyframes", return_value=[]), \
         patch.object(pw, "urlopen", return_value=_http_response(fake_response)):
        result = pw.process_session(fake_homebase, s)

    assert result == "ok"
    assert (s / ".processed").exists()
    assert (fake_homebase / "inbox" / f"{sid}.json").exists()
    inbox_payload = json.loads((fake_homebase / "inbox" / f"{sid}.json").read_text())
    assert inbox_payload["session_id"] == sid


def test_process_session_no_transcript_writes_error(fake_homebase: Path):
    sid = "2026-05-27T10-00-00-notranscript"
    s = _make_session(fake_homebase, sid, mtime_offset=-10)

    with patch.object(pw, "extract_keyframes", return_value=[]), \
         patch.object(pw, "ensure_transcript", return_value=None):
        result = pw.process_session(fake_homebase, s)

    assert result == "error"
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "error"
    assert "no transcript produced" in state["error"]
    assert not (s / ".processed").exists()  # first attempt: do not mark, so it can retry


def test_process_session_no_transcript_gives_up_after_max_attempts(fake_homebase: Path):
    """F9: a permanently silent recording must stop retrying.

    A missing transcript may be transient (the provider still writing), so we retry a few
    times. But a recording with no audio and no provider entry will never transcribe;
    retrying it every 5s forever is the CPU storm that starved keyframe extraction.
    After MAX_TRANSCRIPT_ATTEMPTS, mark .processed and stop.
    """
    sid = "2026-05-27T10-00-00-giveup"
    s = _make_session(fake_homebase, sid, mtime_offset=-10)

    with patch.object(pw, "extract_keyframes", return_value=[]), \
         patch.object(pw, "ensure_transcript", return_value=None):
        # All attempts before the last must NOT mark processed (still retrying)
        for _ in range(pw.MAX_TRANSCRIPT_ATTEMPTS - 1):
            assert pw.process_session(fake_homebase, s) == "error"
            assert not (s / ".processed").exists()
        # The final allowed attempt gives up and marks processed
        assert pw.process_session(fake_homebase, s) == "error"
        assert (s / ".processed").exists()

    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "error"
    assert "gave up" in state["error"]


def test_process_session_langgraph_down_does_not_mark_processed(fake_homebase: Path):
    sid = "2026-05-27T10-00-00-lgdown"
    s = _make_session(fake_homebase, sid, mtime_offset=-10)
    (s / "transcript.json").write_text(json.dumps({"text": "x"}))

    with patch.object(pw, "extract_keyframes", return_value=[]), \
         patch.object(pw, "urlopen", side_effect=OSError("connection refused")):
        result = pw.process_session(fake_homebase, s)

    assert result == "error"
    assert not (s / ".processed").exists()
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert "intake POST failed" in state["error"]


def test_process_session_missing_outputs_marks_processed(fake_homebase: Path):
    sid = "2026-05-27T10-00-00-missing"
    s = _make_session(fake_homebase, sid, mtime_offset=-10)
    (s / "transcript.json").write_text(json.dumps({"text": "x"}))

    fake_response = {
        "session_id": sid,
        "classification": {"deal_type": "x", "sub_type": "y"},
        "library_path": "workflows/library/x",
        "outputs": {"prd": f"prds/{sid}/PRD.md"},  # file does NOT exist
        "pattern_match": {"match": "new"},
    }

    with patch.object(pw, "extract_keyframes", return_value=[]), \
         patch.object(pw, "urlopen", return_value=_http_response(fake_response)):
        result = pw.process_session(fake_homebase, s)

    assert result == "error"
    # This kind of failure is non-retriable (intake said 200 but file is missing).
    assert (s / ".processed").exists()
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert "outputs missing" in state["error"]


def test_find_pending_recordings_accepts_stray_mp4(tmp_path):
    import os as _os
    rec = tmp_path / "recordings" / "sid"
    rec.mkdir(parents=True)
    (rec / "Export.mp4").write_bytes(b"x")
    old = (rec / "Export.mp4").stat().st_mtime - 10
    _os.utime(rec / "Export.mp4", (old, old))
    names = {p.name for p in pw.find_pending_recordings(tmp_path)}
    assert names == {"sid"}


def test_adopt_recording_renames_stray_to_raw(tmp_path):
    rec = tmp_path / "recordings" / "sid"
    rec.mkdir(parents=True)
    (rec / "Export.mp4").write_bytes(b"v")
    out = pw.adopt_recording(rec)
    assert out.name == "raw.mp4" and (rec / "raw.mp4").exists() and not (rec / "Export.mp4").exists()
