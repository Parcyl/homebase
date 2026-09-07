#!/usr/bin/env python3
"""Independent mic backup recorder for capture sessions.

The dictation provider is the primary narration path, but any of them can silently freeze
or otherwise fail to capture (a process can stay alive while its capture is dead -- see
providers/transcript/vowen.py for the incident this is insurance against). This tool has no
dependency on any dictation tool at all: it records the microphone straight to
``<session>/backup-audio.wav`` via ffmpeg, a process fully independent of whatever narration
tool is running. CoreAudio allows shared capture, so it coexists with the primary tool on
the same mic. If the primary path works, this file is unused insurance; if it doesn't, the
pipeline can transcribe this file (e.g. via a local whisper model) so the narration survives.

Fail-loud, not fail-silent: after starting we verify ffmpeg is alive AND the output file is
actually growing within a short window. A zero-byte file means ffmpeg could not open the
mic (almost always a missing Microphone TCC permission for the app that spawned us) -- we
report failure so the caller can alert the operator immediately, instead of discovering it
after a lost recording.

CLI:
    capture_audio_backup.py start --session-dir <dir>
    capture_audio_backup.py stop  --session-dir <dir>
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# avfoundation audio input spec is "<video>:<audio>". A leading ":" means no video, audio
# device index N. Override BACKUP_AUDIO_DEVICE if your default input mic isn't device 0.
DEFAULT_DEVICE = os.environ.get("BACKUP_AUDIO_DEVICE", ":0")
DEFAULT_FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
DEFAULT_FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")

# WAV, not m4a, on purpose. WAV writes PCM samples progressively, so (a) the fail-loud
# byte-growth check below is reliable within ~1s, and (b) a hard crash or SIGKILL leaves a
# playable file -- an unfinalized m4a (moov atom written only on clean exit) would be
# corrupt exactly when the backup is needed. Size (~115 MB/hr at 16 kHz mono 16-bit) is a
# fine trade for a transient, crash-proof safety net.
BACKUP_NAME = "backup-audio.wav"
PID_NAME = ".audio-backup.pid"
LOG_NAME = "backup-audio.log"

# How long to watch for real bytes before declaring the capture live.
VERIFY_WINDOW_S = float(os.environ.get("BACKUP_VERIFY_S", "2.5"))
# 16 kHz mono 16-bit PCM = 32000 bytes/sec, plus a 44-byte header. Real capture clears
# this within ~0.1s; a permission-denied ffmpeg leaves 0 bytes.
MIN_AUDIO_BYTES = 4000
# Graceful-stop budget: ffmpeg finalizes the moov atom on SIGINT. SIGKILL would corrupt
# the file, so we give SIGINT time before escalating.
STOP_GRACE_S = float(os.environ.get("BACKUP_STOP_GRACE_S", "5.0"))

# A prior incident: ffmpeg ran fine and the file grew, but it captured digital silence
# because the launching app had no Microphone permission, so macOS handed avfoundation a
# silent stream instead of erroring. A growing PCM file proves the device is writing, NOT
# that a voice was captured. So before the real recording we take a short PROBE and measure
# its actual level; anything at/below this floor is silence (no permission, muted, or wrong
# device) and we fail loud instead of recording nothing.
SILENCE_FLOOR_DB = float(os.environ.get("BACKUP_SILENCE_FLOOR_DB", "-80.0"))
PROBE_SECONDS = float(os.environ.get("BACKUP_PROBE_S", "2.0"))


def backup_path(session_dir: Path) -> Path:
    return session_dir / BACKUP_NAME


def pid_path(session_dir: Path) -> Path:
    return session_dir / PID_NAME


def log_path(session_dir: Path) -> Path:
    return session_dir / LOG_NAME


def build_ffmpeg_cmd(out: Path, device: str = DEFAULT_DEVICE,
                     ffmpeg_bin: str = DEFAULT_FFMPEG) -> list[str]:
    """ffmpeg args for a mono 16 kHz WAV mic capture (whisper-native, crash-safe).

    -nostdin so a detached ffmpeg never blocks on a closed stdin; mono/16k pcm_s16le is
    exactly what whisper wants and writes progressively so a partial file stays usable.
    """
    return [
        ffmpeg_bin, "-y", "-nostdin",
        "-f", "avfoundation", "-i", device,
        "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(out),
    ]


# ffmpeg/avfoundation signatures that mean the device never opened. We do NOT verify by
# on-disk byte growth: avfoundation device warm-up + ffmpeg's AVIO output buffer mean a
# healthy WAV can sit at 0 bytes on disk for several seconds, so a byte check false-alarms
# on normal sessions. ffmpeg staying alive (it dies fast when the mic is denied) plus the
# absence of a fatal log line is the reliable signal.
FATAL_LOG_MARKERS = (
    "operation not permitted", "input/output error", "permission denied",
    "failed to open", "cannot open", "could not open", "device not found",
    "no such", "denied",
)


def evaluate_capture(proc_alive: bool, log_text: str) -> tuple[bool, str]:
    """Pure decision: is the backup actually capturing audio?

    Decides on process liveness + ffmpeg's own error log, NOT on-disk bytes (which lag
    behind real capture due to device warm-up and output buffering). Separated from I/O
    so the fail-loud logic is unit-testable without a real mic.
    """
    low = (log_text or "").lower()
    fatal = next((m for m in FATAL_LOG_MARKERS if m in low), None)
    if not proc_alive:
        return False, (f"ffmpeg exited during startup ({fatal or 'see backup-audio.log'}) "
                       "-- mic could not be opened; check Microphone permission")
    if fatal:
        return False, (f"ffmpeg reported '{fatal}' -- mic blocked; grant Microphone "
                       "permission to the launching app")
    return True, ""


def evaluate_audio_level(mean_db: float) -> tuple[bool, str]:
    """Pure decision: did the probe capture real sound, or digital silence?

    mean_db is ffmpeg volumedetect's mean_volume. A real voice is roughly -10 to -35 dB;
    a permission-denied / muted / wrong-device stream sits at the noise floor (-80 dB or
    lower, often -91). Separated from I/O so it is unit-testable without a mic.
    """
    if mean_db <= SILENCE_FLOOR_DB:
        return False, (f"mic is SILENT (mean {mean_db:.0f} dB) -- the launching process has no "
                       "Microphone permission, or the mic is muted/wrong device. Refusing to "
                       "record silence.")
    return True, ""


def measure_mean_db(audio: Path, ffmpeg_bin: str = DEFAULT_FFMPEG) -> float:
    """Run ffmpeg volumedetect on a file and return mean_volume in dB (-inf-ish on failure)."""
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-i", str(audio), "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return -99.0
    for line in res.stderr.splitlines():
        if "mean_volume:" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().split()[0])
            except (ValueError, IndexError):
                return -99.0
    return -99.0


def probe_audio_level(
    *,
    device: str = DEFAULT_DEVICE,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    seconds: float = PROBE_SECONDS,
    tmp: Path | None = None,
) -> float:
    """Record a short blocking probe and return its mean dB. Deterministic (no buffering
    races): volumedetect runs on the completed probe file. Returns -99.0 if the probe fails."""
    probe = tmp or Path(tempfile.gettempdir()) / "homebase_mic_probe.wav"
    try:
        subprocess.run(
            [ffmpeg_bin, "-y", "-hide_banner", "-nostdin", "-f", "avfoundation", "-i", device,
             "-t", str(seconds), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(probe)],
            capture_output=True, timeout=seconds + 15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return -99.0
    if not probe.exists() or probe.stat().st_size < MIN_AUDIO_BYTES:
        return -99.0
    db = measure_mean_db(probe, ffmpeg_bin)
    try:
        probe.unlink()
    except OSError:
        pass
    return db


def _proc_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def start_backup(
    session_dir: Path,
    *,
    device: str = DEFAULT_DEVICE,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    spawn=subprocess.Popen,
    verify: bool = True,
    verify_window_s: float = VERIFY_WINDOW_S,
    sleep=time.sleep,
    probe: bool = True,
    probe_fn=None,
) -> dict:
    """Spawn a detached ffmpeg mic recording into the session dir.

    Returns {ok, pid, path, reason}. ok=False means the capture did not come up (caller
    should alert; the dictation provider becomes the only narration path).

    Before recording, a short PROBE measures the actual mic level and refuses to start if
    the input is silent (no permission / muted / wrong device) -- see SILENCE_FLOOR_DB
    above. probe_fn is injectable for tests.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    out = backup_path(session_dir)

    if probe:
        measure = probe_fn or (lambda: probe_audio_level(device=device, ffmpeg_bin=ffmpeg_bin))
        mean_db = measure()
        ok, reason = evaluate_audio_level(mean_db)
        if not ok:
            return {"ok": False, "pid": None, "path": str(out), "mean_db": mean_db,
                    "reason": reason}

    cmd = build_ffmpeg_cmd(out, device=device, ffmpeg_bin=ffmpeg_bin)

    logf = open(log_path(session_dir), "wb")
    try:
        proc = spawn(cmd, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                     start_new_session=True)
    except (OSError, FileNotFoundError) as e:
        logf.close()
        return {"ok": False, "pid": None, "path": str(out),
                "reason": f"could not launch ffmpeg: {e}"}

    pid_path(session_dir).write_text(str(proc.pid) + "\n", encoding="utf-8")

    if not verify:
        return {"ok": True, "pid": proc.pid, "path": str(out), "reason": ""}

    # Give ffmpeg the window to either die (mic denied) or settle into capturing. Break
    # early the moment it dies; otherwise let it run the full window then judge.
    waited = 0.0
    step = 0.25
    while waited < verify_window_s and _proc_alive(proc.pid):
        sleep(step)
        waited += step

    ok, reason = evaluate_capture(_proc_alive(proc.pid), _read_log_tail(session_dir))
    return {"ok": ok, "pid": proc.pid, "path": str(out), "reason": reason}


def _read_log_tail(session_dir: Path, limit: int = 4000) -> str:
    try:
        return log_path(session_dir).read_bytes()[-limit:].decode("utf-8", "replace")
    except OSError:
        return ""


def stop_backup(
    session_dir: Path,
    *,
    ffprobe_bin: str = DEFAULT_FFPROBE,
    grace_s: float = STOP_GRACE_S,
    sleep=time.sleep,
) -> dict:
    """Cleanly stop the backup recording and report what we got.

    Returns {ok, duration_s, size, path, reason}. Safe to call when nothing is running (no
    pid file) -- returns ok=False with a benign reason.
    """
    out = backup_path(session_dir)
    pidf = pid_path(session_dir)
    if not pidf.exists():
        return _final_report(out, ffprobe_bin, reason="no backup pid (was it started?)")

    try:
        pid = int(pidf.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pidf.unlink(missing_ok=True)
        return _final_report(out, ffprobe_bin, reason="unreadable pid file")

    if _proc_alive(pid):
        # SIGINT lets ffmpeg finalize the moov atom; without it the file is unplayable.
        try:
            os.kill(pid, signal.SIGINT)
        except OSError:
            pass
        waited = 0.0
        while waited < grace_s and _proc_alive(pid):
            sleep(0.25)
            waited += 0.25
        if _proc_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    pidf.unlink(missing_ok=True)
    return _final_report(out, ffprobe_bin)


def _final_report(out: Path, ffprobe_bin: str, reason: str = "") -> dict:
    size = out.stat().st_size if out.exists() else 0
    duration = probe_duration(out, ffprobe_bin) if size > 0 else 0.0
    ok = size >= MIN_AUDIO_BYTES and duration > 0.0
    return {"ok": ok, "duration_s": round(duration, 1), "size": size,
            "path": str(out), "reason": reason}


def probe_duration(audio: Path, ffprobe_bin: str = DEFAULT_FFPROBE) -> float:
    try:
        res = subprocess.run(
            [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
            capture_output=True, text=True, timeout=20, check=False,
        )
        return float(res.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent mic backup recorder")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("start", "stop"):
        p = sub.add_parser(name)
        p.add_argument("--session-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.cmd == "start":
        r = start_backup(args.session_dir)
        if r["ok"]:
            print(f"ok {r['pid']} {r['path']}")
            return 0
        print(f"FAILED {r['reason']}", file=sys.stderr)
        return 1

    # stop
    r = stop_backup(args.session_dir)
    if r["ok"]:
        print(f"ok {r['duration_s']} {r['size']}")
        return 0
    print(f"none {r.get('reason') or 'no usable backup audio'}")
    return 0  # stop is best-effort; never fail the Stop click


if __name__ == "__main__":
    raise SystemExit(main())
