"""Tests for ScreenStudioRecorder: bundle matching + AppleScript control.

All live-system calls (osascript, bundle mtimes) are injectable so these never need a real
Screen Studio install; see ScreenStudioRecorder's `runner` and find_screenstudio_master's
`time_fn`.
"""
from __future__ import annotations

from pathlib import Path

from providers.recorder.screen_studio import (
    ScreenStudioRecorder,
    find_screenstudio_master,
)


def _mk_bundle(ss_dir: Path, name: str) -> Path:
    b = ss_dir / f"{name}.screenstudio"
    (b / "recording").mkdir(parents=True)
    m = b / "recording" / "channel-1-display-0.mp4"
    m.write_bytes(b"video")
    return m


def test_find_screenstudio_master_picks_closest_in_time(tmp_path):
    ss = tmp_path / "ss"
    ss.mkdir()
    m1 = _mk_bundle(ss, "a")
    m2 = _mk_bundle(ss, "b")
    times = {str(m1): 1000.0, str(m2): 1050.0}
    got = find_screenstudio_master(1040.0, ss_dir=ss, tolerance_s=600,
                                   time_fn=lambda p: times[str(p)])
    assert got == m2  # 1050 is nearer to 1040 than 1000


def test_find_screenstudio_master_none_outside_tolerance(tmp_path):
    ss = tmp_path / "ss"
    ss.mkdir()
    _mk_bundle(ss, "a")
    got = find_screenstudio_master(1000.0, ss_dir=ss, tolerance_s=60, time_fn=lambda p: 9000.0)
    assert got is None  # never adopt a video that does not match the session time


def test_find_screenstudio_master_none_when_no_start_epoch():
    assert find_screenstudio_master(0.0, ss_dir=Path("/nonexistent")) is None


def test_find_screenstudio_master_none_when_dir_missing(tmp_path):
    assert find_screenstudio_master(1000.0, ss_dir=tmp_path / "nope") is None


def test_resolve_master_delegates_to_find_screenstudio_master(tmp_path):
    ss = tmp_path / "ss"
    ss.mkdir()
    m = _mk_bundle(ss, "only")
    recorder = ScreenStudioRecorder(ss_dir=ss, tolerance_s=600, runner=lambda *_: None)
    got = recorder.resolve_master(m.stat().st_mtime, tmp_path / "session")
    assert got == m


def test_start_invokes_runner_with_start_script(tmp_path):
    calls = []
    recorder = ScreenStudioRecorder(runner=lambda script: calls.append(script))
    recorder.start(tmp_path)
    assert len(calls) == 1
    assert calls[0].name == "screen_studio_start.applescript"


def test_stop_invokes_runner_with_stop_script(tmp_path):
    calls = []
    recorder = ScreenStudioRecorder(runner=lambda script: calls.append(script))
    recorder.stop(tmp_path)
    assert len(calls) == 1
    assert calls[0].name == "screen_studio_stop.applescript"


def test_applescript_files_exist_next_to_module():
    from providers.recorder.screen_studio import START_SCRIPT, STOP_SCRIPT
    assert START_SCRIPT.exists()
    assert STOP_SCRIPT.exists()
