"""Pipeline watcher daemon.

Watches <homebase>/recordings/ for new raw.mp4 files. For each new recording:
- runs ffmpeg keyframe extraction
- uses an existing transcript.json or asks the configured TranscriptProvider
  (see providers/transcript/) for the session's narration, via record_session.py's
  deferred capture
- POSTs the payload to the intelligence spine's /intake endpoint (see intelligence/)
- verifies output paths exist on disk
- drops the response in inbox/<session_id>.json for downstream consumers
- touches <session_dir>/.processed to prevent re-processing

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent

POLL_INTERVAL_S = 5
RECORDING_SETTLE_S = 2

# Keyframe extraction: a fixed, bounded number of evenly-spaced frames, sampled by
# fast input seek. This is length-independent (a 36-minute recording yields the same
# count as a 2-minute one) and avoids decoding the whole video to write ~1,096 frames
# of which the intelligence spine's extract node uses only 10. See post-mortem 2026-06-01.
KEYFRAME_COUNT = 15

# A missing transcript may be transient (the dictation provider still flushing its entry),
# so retry a few times. But a silent recording with no provider entry will never
# transcribe; after this many attempts we mark the session processed and stop, rather than
# re-running the full pipeline every poll forever (the CPU storm from the 2026-06-01
# post-mortem).
MAX_TRANSCRIPT_ATTEMPTS = 3

# The /intake call runs the whole intelligence spine (several sequential Claude calls). A
# single transient Anthropic 520 forces a 60s SDK backoff, which on top of normal graph time
# can blow past a tight client timeout. The watcher then closes the socket, the server
# cancels the in-flight graph, and a fully-working pipeline produces no PRD (post-mortem
# 2026-06-09). 1200s gives generous headroom for the graph plus a couple of API retries.
DEFAULT_POST_TIMEOUT_S = int(os.environ.get("LANGGRAPH_POST_TIMEOUT_S", "1200"))

# Timeout for the deferred TranscriptProvider capture subprocess (record_session.py
# capture). Matches doc_generator.py's ensure_transcript, which shells out to the same
# script for the same reason.
TRANSCRIPT_CAPTURE_TIMEOUT_S = int(os.environ.get("TRANSCRIPT_CAPTURE_TIMEOUT_S", "300"))

SESSIONS_DIR = os.environ.get("SESSIONS_DIR", "recordings")

DEFAULT_HOMEBASE = Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT)))
DEFAULT_LANGGRAPH = os.environ.get("LANGGRAPH_URL", "http://127.0.0.1:8080")
DEFAULT_FFMPEG = os.environ.get("FFMPEG_BIN", "ffmpeg")
DEFAULT_FFPROBE = os.environ.get("FFPROBE_BIN", "ffprobe")
DEFAULT_PYTHON = os.environ.get("PYTHON_BIN", sys.executable or "python3")

log = logging.getLogger("homebase.pipeline_watcher")


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_state(
    homebase: Path,
    stage: str,
    session_id: str | None = None,
    **extra: Any,
) -> None:
    """Atomic write to agents/pipeline-state.json -- the shared state contract also read
    and written by intelligence/app/pipeline_state.py (see that module's docstring)."""
    path = homebase / "agents" / "pipeline-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict[str, Any] = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8")) or {}
            if not isinstance(current, dict):
                current = {}
        except (OSError, json.JSONDecodeError):
            current = {}

    current["stage"] = stage
    if session_id is not None:
        current["session_id"] = session_id
    current["updated_at"] = _now_iso()
    if stage != "error":
        if stage in {"recording", "ready"}:
            current["error"] = current.get("error")
        else:
            current["error"] = None
    for key, value in extra.items():
        current[key] = value

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def session_mp4(session_dir: Path) -> Path | None:
    """The session's recording. Prefer raw.mp4; else the largest stray *.mp4.

    Some recorders export under their own name (not raw.mp4), so requiring the exact name
    would force a manual rename on every recording. Accept any *.mp4 and adopt it (see
    adopt_recording).
    """
    raw = session_dir / "raw.mp4"
    if raw.exists():
        return raw
    mp4s = [p for p in session_dir.glob("*.mp4") if p.is_file()]
    return max(mp4s, key=lambda p: p.stat().st_size) if mp4s else None


def adopt_recording(session_dir: Path) -> Path | None:
    """Ensure raw.mp4 exists, renaming a stray export once. Returns raw.mp4."""
    raw = session_dir / "raw.mp4"
    if raw.exists():
        return raw
    found = session_mp4(session_dir)
    if found is None:
        return None
    try:
        found.rename(raw)
        log.info("adopted_recording renamed=%s session_id=%s", found.name, session_dir.name)
        return raw
    except OSError:
        return found


def find_pending_recordings(homebase: Path) -> list[Path]:
    """Return session dirs that have a stable recording (.mp4) and no .processed marker."""
    recordings = homebase / SESSIONS_DIR
    if not recordings.exists():
        return []
    pending: list[Path] = []
    now = time.time()
    for session_dir in sorted(recordings.iterdir()):
        if not session_dir.is_dir():
            continue
        mp4 = session_mp4(session_dir)
        if mp4 is None:
            continue
        if (session_dir / ".processed").exists():
            continue
        try:
            age = now - mp4.stat().st_mtime
        except OSError:
            continue
        if age < RECORDING_SETTLE_S:
            continue
        pending.append(session_dir)
    return pending


def _probe_duration(mp4: Path, ffprobe_bin: str = DEFAULT_FFPROBE) -> float | None:
    """Return the video duration in seconds, or None if it can't be determined."""
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(mp4),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        duration = float(out.stdout.decode("utf-8", "replace").strip())
        return duration if duration > 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError) as e:
        log.warning("ffprobe_duration_failed err=%s", e)
        return None


def extract_keyframes(
    mp4: Path,
    keyframes_dir: Path,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    count: int = KEYFRAME_COUNT,
    ffprobe_bin: str = DEFAULT_FFPROBE,
) -> list[str]:
    """Extract a bounded set of evenly-spaced keyframes via fast input seek.

    Each frame is grabbed with `-ss <t> -i <mp4> -frames:v 1`, which seeks rather
    than decoding the whole file. The count is fixed (KEYFRAME_COUNT) regardless of
    recording length, so a 36-minute walkthrough no longer produces ~1,096 frames to
    use 10. Frames are sampled at the centre of each of `count` equal segments to avoid
    the very first and last frames.

    If the duration cannot be read, falls back to a single frame at the start.
    Best-effort; never raises. Logs the produced count so a short result is visible
    instead of silently degrading the vision leg (post-mortem 2026-06-01).
    """
    keyframes_dir.mkdir(parents=True, exist_ok=True)
    duration = _probe_duration(mp4, ffprobe_bin)
    if duration:
        timestamps = [duration * (i + 0.5) / count for i in range(count)]
    else:
        timestamps = [0.0]

    for idx, t in enumerate(timestamps, start=1):
        cmd = [
            ffmpeg_bin,
            "-y",
            "-ss", f"{t:.3f}",
            "-i", str(mp4),
            "-frames:v", "1",
            "-q:v", "2",
            str(keyframes_dir / f"kf_{idx:04d}.jpg"),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=60, check=False)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            log.warning("ffmpeg_keyframe_failed t=%.3f err=%s", t, e)

    frames = sorted(str(p) for p in keyframes_dir.glob("*.jpg"))
    log.info(
        "keyframes_extracted produced=%d expected=%d duration=%s",
        len(frames), len(timestamps), duration,
    )
    return frames


def ensure_transcript(
    session_dir: Path,
    python_bin: str = DEFAULT_PYTHON,
) -> Any | None:
    """Load an existing transcript.json or run the deferred TranscriptProvider capture.

    Returns the parsed transcript (dict, list, or str) or None on total failure.
    """
    transcript_path = session_dir / "transcript.json"
    if transcript_path.exists():
        try:
            return json.loads(transcript_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            try:
                return transcript_path.read_text(encoding="utf-8")
            except OSError:
                return None

    # Deferred provider capture. A flush-prone dictation tool (see providers/transcript/vowen.py)
    # may not have written its narration by the time recording stopped, so record_session.py
    # persists the session window to session.json and re-queries the configured
    # TranscriptProvider here, after the tool has had time to flush. See the 2026-06-09
    # post-mortem this guards against.
    record_script = _HERE / "record_session.py"
    if record_script.exists() and (session_dir / "session.json").exists():
        try:
            subprocess.run(
                [python_bin, str(record_script), "capture",
                 "--session", session_dir.name, "--homebase", str(session_dir.parent.parent),
                 "--sessions-dir", SESSIONS_DIR],
                capture_output=True, timeout=TRANSCRIPT_CAPTURE_TIMEOUT_S, check=False,
            )
        except subprocess.TimeoutExpired:
            log.error("transcript_capture_timeout session_id=%s after %ss",
                       session_dir.name, TRANSCRIPT_CAPTURE_TIMEOUT_S)
        except (FileNotFoundError, OSError) as e:
            log.warning("transcript_capture_failed session_id=%s err=%s", session_dir.name, e)
        if transcript_path.exists():
            try:
                return json.loads(transcript_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass

    mp4 = session_dir / "raw.mp4"
    if not mp4.exists():
        return None

    # Last-resort fallback: transcribe the video itself with mlx-whisper (bring-your-own
    # optional dependency; a missing/failing install just means no transcript, not a crash).
    cmd = [
        python_bin, "-m", "mlx_whisper",
        str(mp4),
        "--output-format", "json",
        "--output-dir", str(session_dir),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=1200, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        log.warning("mlx_whisper_failed err=%s", e)
        return None

    # mlx_whisper writes <stem>.json based on the input filename (raw.json)
    candidate = session_dir / "raw.json"
    if candidate.exists():
        try:
            candidate.rename(transcript_path)
            return json.loads(transcript_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
    return None


def post_to_langgraph(
    payload: dict,
    url: str = DEFAULT_LANGGRAPH,
    timeout: int = DEFAULT_POST_TIMEOUT_S,
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        f"{url}/intake",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _bump_attempts(session_dir: Path) -> int:
    """Increment and return the per-session transcript attempt counter.

    Persisted in <session>/.attempts so the count survives across watcher poll
    iterations (and watcher restarts). Used to bound retries on a missing transcript.
    """
    marker = session_dir / ".attempts"
    try:
        current = int(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        current = 0
    current += 1
    try:
        marker.write_text(str(current), encoding="utf-8")
    except OSError:
        pass
    return current


def process_session(
    homebase: Path,
    session_dir: Path,
    langgraph_url: str = DEFAULT_LANGGRAPH,
    ffmpeg_bin: str = DEFAULT_FFMPEG,
    python_bin: str = DEFAULT_PYTHON,
) -> str:
    """Run one session through the pipeline. Returns the final stage.

    Marks .processed only when the intelligence spine claims success (200 + outputs).
    Transient failures (server down) leave .processed absent so the next poll
    retries. A missing transcript is retried up to MAX_TRANSCRIPT_ATTEMPTS times
    (the dictation provider may still be flushing), then given up on and marked processed
    so a silent recording does not loop the full pipeline forever.
    """
    session_id = session_dir.name
    log.info("process_start session_id=%s", session_id)
    update_state(homebase, "transcribing", session_id, message="transcript + keyframes")

    # Adopt a stray export -> raw.mp4 so no manual rename is needed.
    adopt_recording(session_dir)
    mp4 = session_dir / "raw.mp4"

    # Transcript first (cheap): a missing transcript aborts the run, so there is no
    # point paying for keyframe extraction on a doomed pass.
    transcript = ensure_transcript(session_dir, python_bin)
    if not transcript:
        attempts = _bump_attempts(session_dir)
        if attempts >= MAX_TRANSCRIPT_ATTEMPTS:
            update_state(
                homebase, "error", session_id,
                error=(
                    f"pipeline_watcher: no transcript produced after {attempts} attempts; "
                    "gave up (no provider entry and the whisper fallback failed). Recording "
                    "likely has no audio."
                ),
            )
            (session_dir / ".processed").touch()  # stop retrying a permanent failure
            return "error"
        update_state(
            homebase, "error", session_id,
            error=(
                f"pipeline_watcher: no transcript produced "
                f"(attempt {attempts}/{MAX_TRANSCRIPT_ATTEMPTS}); will retry"
            ),
        )
        return "error"

    keyframes = extract_keyframes(mp4, session_dir / "keyframes", ffmpeg_bin)

    payload = {
        "session_id": session_id,
        "recording_path": str(mp4),
        "transcript": transcript,
        "keyframe_paths": keyframes,
        "context_cue": None,
    }

    try:
        response = post_to_langgraph(payload, langgraph_url)
    except (URLError, TimeoutError, OSError) as e:
        update_state(homebase, "error", session_id, error=f"pipeline_watcher: intake POST failed: {e}")
        return "error"

    outputs = response.get("outputs") or {}
    missing = [k for k, rel in outputs.items() if not (homebase / rel).exists()]
    if missing:
        update_state(
            homebase, "error", session_id,
            error=f"pipeline_watcher: intake returned 200 but outputs missing: {missing}",
        )
        (session_dir / ".processed").touch()  # do not retry on this kind of failure
        return "error"

    inbox = homebase / "inbox" / f"{session_id}.json"
    inbox.parent.mkdir(parents=True, exist_ok=True)
    inbox.write_text(json.dumps(response, indent=2) + "\n", encoding="utf-8")

    (session_dir / ".processed").touch()
    log.info("process_done session_id=%s prd=%s", session_id, outputs.get("prd"))
    return "ok"


def main_loop(
    homebase: Path,
    langgraph_url: str = DEFAULT_LANGGRAPH,
) -> None:
    log.info(
        "pipeline_watcher_start homebase=%s langgraph=%s",
        homebase, langgraph_url,
    )
    while True:
        try:
            for session_dir in find_pending_recordings(homebase):
                process_session(homebase, session_dir, langgraph_url)
        except Exception:
            log.exception("watcher_loop_error")
        time.sleep(POLL_INTERVAL_S)


def _setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stdout,
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
    )


def cli() -> None:
    parser = argparse.ArgumentParser(description="homebase pipeline watcher")
    parser.add_argument("--homebase", type=Path, default=DEFAULT_HOMEBASE)
    parser.add_argument("--langgraph-url", default=DEFAULT_LANGGRAPH)
    parser.add_argument("--once", action="store_true", help="Process pending sessions once and exit")
    args = parser.parse_args()

    _setup_logging()

    if args.once:
        for session_dir in find_pending_recordings(args.homebase):
            process_session(args.homebase, session_dir, args.langgraph_url)
        return

    main_loop(args.homebase, args.langgraph_url)


if __name__ == "__main__":
    cli()
