"""Tests for the independent mic backup recorder (capture_audio_backup).

These exercise the REAL guarantees without a real mic:
- The fail-loud decision (dead ffmpeg / zero bytes -> not ok) is a pure function.
- start_backup writes a pid file and reports ok only when bytes are actually landing.
- stop_backup is safe when nothing was started, and removes the pid file on a clean stop.
"""
from __future__ import annotations

import os
from pathlib import Path

import capture_audio_backup as cab


# ---------- pure decision: is it actually capturing? ----------

def test_evaluate_capture_dead_process_fails():
    ok, reason = cab.evaluate_capture(proc_alive=False, log_text="")
    assert not ok and "exited" in reason.lower()


def test_evaluate_capture_fatal_log_marker_fails_even_if_alive():
    # The dangerous case: ffmpeg still alive but the log shows the mic was denied.
    ok, reason = cab.evaluate_capture(proc_alive=True, log_text="[avfoundation] Operation not permitted")
    assert not ok and "permission" in reason.lower()


def test_evaluate_capture_alive_clean_log_ok():
    # Healthy ffmpeg: alive, progress in the log, no fatal marker. Bytes-on-disk are NOT
    # required (they lag behind real capture) -- this is the regression guard for the
    # false-negative that cried "mic permission" on a working 5.7s capture.
    ok, reason = cab.evaluate_capture(proc_alive=True, log_text="size=  128kB time=00:00:02.0 bitrate=...")
    assert ok and reason == ""


# ---------- level guard: never record silence ----------

def test_evaluate_audio_level_silence_fails():
    # 42 min of digital silence measured -91 dB; the guard must reject it.
    ok, reason = cab.evaluate_audio_level(-91.0)
    assert not ok and "silent" in reason.lower()


def test_evaluate_audio_level_real_voice_ok():
    ok, reason = cab.evaluate_audio_level(-20.0)
    assert ok and reason == ""


def test_evaluate_audio_level_floor_is_inclusive():
    # exactly at the floor counts as silent (no real signal sits at the floor)
    ok, _ = cab.evaluate_audio_level(cab.SILENCE_FLOOR_DB)
    assert not ok


def test_start_backup_refuses_silent_mic_without_spawning(tmp_path):
    # The whole point: if the probe is silent, do NOT spawn ffmpeg and do NOT record.
    def boom_spawn(*a, **k):
        raise AssertionError("ffmpeg must not be spawned when the mic is silent")

    r = cab.start_backup(tmp_path, spawn=boom_spawn, probe_fn=lambda: -91.0)
    assert r["ok"] is False
    assert "silent" in r["reason"].lower()
    assert not cab.backup_path(tmp_path).exists()


def test_start_backup_proceeds_when_probe_has_sound(tmp_path):
    def fake_spawn(cmd, **kw):
        return _FakeProc(os.getpid())

    r = cab.start_backup(tmp_path, spawn=fake_spawn, probe_fn=lambda: -22.0,
                         verify_window_s=0.3, sleep=lambda _s: None)
    assert r["ok"] is True


# ---------- ffmpeg command shape ----------

def test_build_ffmpeg_cmd_is_mono_16k_to_output(tmp_path):
    out = tmp_path / "backup-audio.wav"
    cmd = cab.build_ffmpeg_cmd(out, device=":0", ffmpeg_bin="ffmpeg")
    assert "avfoundation" in cmd and ":0" in cmd
    assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
    assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
    assert cmd[-1] == str(out)


# ---------- start: fake spawn, no real ffmpeg ----------

class _FakeProc:
    def __init__(self, pid: int):
        self.pid = pid


def test_start_backup_reports_ok_when_ffmpeg_stays_alive(tmp_path):
    def fake_spawn(cmd, **kw):
        return _FakeProc(os.getpid())  # current process: definitely alive, clean log

    r = cab.start_backup(tmp_path, spawn=fake_spawn, verify_window_s=0.5,
                         sleep=lambda _s: None, probe=False)
    assert r["ok"] is True
    assert cab.pid_path(tmp_path).exists()
    assert cab.pid_path(tmp_path).read_text().strip() == str(os.getpid())


def test_start_backup_fails_loud_when_ffmpeg_dies(tmp_path):
    dead_pid = 2_000_000_000  # not a live process

    def fake_spawn(cmd, **kw):
        return _FakeProc(dead_pid)  # never writes a file

    r = cab.start_backup(tmp_path, spawn=fake_spawn, verify_window_s=0.5,
                         sleep=lambda _s: None, probe=False)
    assert r["ok"] is False
    assert r["reason"]  # a human-readable reason for the operator


# ---------- stop: safe and clean ----------

def test_stop_backup_no_pid_is_safe(tmp_path):
    r = cab.stop_backup(tmp_path)
    assert r["ok"] is False  # nothing to stop
    assert "pid" in (r.get("reason") or "").lower()


def test_stop_backup_clean_removes_pid(tmp_path, monkeypatch):
    # A dead pid (already exited) + a real-looking file -> clean finalize.
    cab.backup_path(tmp_path).write_bytes(b"\x00" * (cab.MIN_AUDIO_BYTES + 10))
    cab.pid_path(tmp_path).write_text("2000000001\n")  # not alive
    monkeypatch.setattr(cab, "probe_duration", lambda *a, **k: 7.5)

    r = cab.stop_backup(tmp_path, sleep=lambda _s: None)
    assert r["ok"] is True and r["duration_s"] == 7.5
    assert not cab.pid_path(tmp_path).exists()
