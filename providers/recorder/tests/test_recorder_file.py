"""Tests for FileRecorder: the default, bring-your-own recorder adapter."""
from __future__ import annotations

from providers.recorder.file import FileRecorder


def test_resolve_master_none_when_session_dir_empty(tmp_path):
    recorder = FileRecorder()
    assert recorder.resolve_master(1000.0, tmp_path) is None


def test_resolve_master_finds_a_dropped_mp4(tmp_path):
    (tmp_path / "Area.mp4").write_bytes(b"video")
    recorder = FileRecorder()
    got = recorder.resolve_master(1000.0, tmp_path)
    assert got == tmp_path / "Area.mp4"


def test_resolve_master_prefers_existing_raw_mp4(tmp_path):
    (tmp_path / "Area.mp4").write_bytes(b"stray")
    (tmp_path / "raw.mp4").write_bytes(b"canonical")
    recorder = FileRecorder()
    assert recorder.resolve_master(1000.0, tmp_path) == tmp_path / "raw.mp4"


def test_resolve_master_picks_largest_stray_mp4(tmp_path):
    (tmp_path / "small.mp4").write_bytes(b"x" * 5)
    (tmp_path / "big.mp4").write_bytes(b"x" * 50)
    recorder = FileRecorder()
    assert recorder.resolve_master(1000.0, tmp_path).name == "big.mp4"


def test_start_stop_are_noops(tmp_path):
    recorder = FileRecorder()
    # no exception, no side effect -- nothing to control
    recorder.start(tmp_path)
    recorder.stop(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_is_running_is_none_not_false():
    """No process to check -- None ('not applicable'), never False ('not running'), so the
    healthcheck knows to skip the check rather than block every session on it."""
    recorder = FileRecorder()
    assert recorder.is_running() is None
