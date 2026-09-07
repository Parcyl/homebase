"""Start/Stop recording-session markers, with stop-time narration capture via a
TranscriptProvider (see providers/transcript/).

The manual recording flow records video in a screen recorder and voice in a dictation tool,
two tools that do not share a session boundary. The only moment a dictation tool's newest
entries are unambiguously this recording's narration is the window between start and stop.
So:

  start  -> create <sessions_dir>/<session_id>/ and remember the start time
  ...record with your recorder + narrate with your dictation provider...
  stop   -> ask the configured TranscriptProvider for everything in that window, write
            transcript.json into the session

Then export the recording to <sessions_dir>/<session_id>/raw.mp4 and the pipeline watcher
does the rest. The watcher must NOT guess the transcript later by re-reading a moving
history file at an arbitrary time -- the window is fixed at stop and persisted to
session.json, and capture_session() re-applies that same fixed window (see capture_session's
docstring for why this is deferred rather than done here).

Pure stdlib except for the providers/ import.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from providers.transcript import TranscriptEntry, TranscriptProvider, get_provider  # noqa: E402

# No HOMEBASE_ROOT env override -> fall back to the repo root (one level up from this
# file: pipeline/ -> repo root).
DEFAULT_HOMEBASE = Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT)))
# The deal flow records into recordings/. A second, independent flow can record into its
# own sessions dir instead (e.g. a separate bug-capture flow), so a watcher polling only
# "recordings" never sees it. The sessions dir is a parameter; "recordings" is the default.
DEFAULT_SESSIONS_DIR = "recordings"
MARKER_NAME = ".rec-session.json"
# Persisted alongside the recording so the session window survives the marker being
# cleared at stop. The watcher reads this to re-capture narration at process time, after
# the dictation tool has flushed.
SESSION_META_NAME = "session.json"
# Small tolerance so an entry whose dictation started a beat before the start click is
# still included in the window.
START_TOLERANCE_S = 5.0
# Grace past stop so a tool that flushes its final entry a beat late isn't truncated.
FLUSH_GRACE_S = 120.0


class NoActiveSession(Exception):
    """Raised when stop is called with no active start marker."""


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def make_session_id(now: datetime, slug: str | None = None) -> str:
    """Date-first id matching the watcher/intake regex, with an optional slug."""
    base = now.strftime("%Y-%m-%dT%H-%M-%S")
    if slug:
        s = _slugify(slug)
        if s:
            return f"{base}-{s}"
    return base


def marker_path(homebase: Path, sessions_dir: str = DEFAULT_SESSIONS_DIR) -> Path:
    """Active-session marker. The default sessions dir keeps the original marker name so
    the default flow is unchanged; any other sessions dir gets its own marker so two
    concurrent session flows can never clobber each other's start/stop state.
    """
    if sessions_dir == DEFAULT_SESSIONS_DIR:
        return homebase / "agents" / MARKER_NAME
    suffix = _slugify(sessions_dir) or "alt"
    return homebase / "agents" / f".rec-session-{suffix}.json"


def _session_meta_path(homebase: Path, session_id: str, sessions_dir: str = DEFAULT_SESSIONS_DIR) -> Path:
    return homebase / sessions_dir / session_id / SESSION_META_NAME


def _write_session_meta(
    homebase: Path, session_id: str, sessions_dir: str = DEFAULT_SESSIONS_DIR, **fields: object
) -> None:
    """Merge fields into <sessions_dir>/<id>/session.json (atomic-ish, best-effort)."""
    path = _session_meta_path(homebase, session_id, sessions_dir)
    current: dict = {}
    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
    current.update({"session_id": session_id, **fields})
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: the watcher may read this concurrently at process time.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def start_session(
    homebase: Path = DEFAULT_HOMEBASE,
    now: datetime | None = None,
    slug: str | None = None,
    sessions_dir: str = DEFAULT_SESSIONS_DIR,
) -> str:
    """Create the session dir and write the start marker. Returns the session id.

    The default `now` is local wall-clock (timezone-aware) so the session folder name
    matches the clock the operator sees. The stored start_epoch is timezone-agnostic, so
    provider windowing is unaffected.
    """
    now = now or datetime.now().astimezone()
    session_id = make_session_id(now, slug)
    (homebase / sessions_dir / session_id).mkdir(parents=True, exist_ok=True)
    marker = marker_path(homebase, sessions_dir)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "session_id": session_id,
                "start_epoch": now.timestamp(),
                "start_iso": now.isoformat(),
                "sessions_dir": sessions_dir,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # Persist the window with the recording too, so the watcher can re-capture the
    # narration after the marker is cleared at stop.
    _write_session_meta(
        homebase, session_id, sessions_dir,
        start_epoch=now.timestamp(), start_iso=now.isoformat(),
    )
    return session_id


def build_transcript(entries: list[TranscriptEntry]) -> dict | None:
    """Concatenate entry texts chronologically into a transcript dict, or None if empty.

    Provider-agnostic: `source` reflects whichever provider supplied the entries, not a
    hardcoded tool name.
    """
    texts = [e.text.strip() for e in entries if e.text and e.text.strip()]
    if not texts:
        return None
    return {
        "text": "\n\n".join(texts),
        "source": entries[0].source if entries else "unknown",
        "entry_count": len(texts),
        "timestamps": [e.ts_iso for e in entries],
    }


def stop_session(
    homebase: Path = DEFAULT_HOMEBASE,
    provider: TranscriptProvider | None = None,
    now: datetime | None = None,
    sessions_dir: str = DEFAULT_SESSIONS_DIR,
) -> dict:
    """End the session: record the stop time and best-effort capture the narration.

    Persists stop_epoch to session.json so the watcher can re-capture the provider's window
    later, after the dictation tool has flushed. The stop-time capture is best-effort: the
    final narration entry often has not flushed yet, so transcript.json is commonly written
    by the watcher's deferred capture, not here. Clears the start marker either way.
    Raises NoActiveSession if start was never called.

    `provider` defaults to the configured TranscriptProvider (DICTATION_PROVIDER env),
    built once the session dir is known so FileProvider can bind to it.
    """
    now = now or datetime.now().astimezone()
    marker = marker_path(homebase, sessions_dir)
    try:
        meta = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise NoActiveSession("no active recording session (run start first)") from e

    session_id = meta["session_id"]
    start_epoch = float(meta["start_epoch"])
    stop_epoch = now.timestamp()
    session_dir = homebase / sessions_dir / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Record the window bounds with the recording before anything else, so a re-capture
    # is possible even if this process dies here.
    _write_session_meta(
        homebase, session_id, sessions_dir,
        start_epoch=start_epoch, stop_epoch=stop_epoch, stop_iso=now.isoformat(),
    )

    active_provider = provider or get_provider(session_dir=session_dir)
    entries = active_provider.entries_in_window(
        start_epoch, stop_epoch, tolerance_s=START_TOLERANCE_S, grace_s=FLUSH_GRACE_S)
    transcript = build_transcript(entries)
    transcript_path = session_dir / "transcript.json"
    if transcript:
        transcript_path.write_text(json.dumps(transcript, indent=2) + "\n", encoding="utf-8")

    try:
        marker.unlink()
    except OSError:
        pass

    return {
        "session_id": session_id,
        "entry_count": transcript["entry_count"] if transcript else 0,
        "transcript_path": str(transcript_path) if transcript else None,
        "deferred": transcript is None,  # watcher will capture at process time
        "raw_target": str(session_dir / "raw.mp4"),
    }


def capture_session(
    homebase: Path = DEFAULT_HOMEBASE,
    session_id: str = "",
    provider: TranscriptProvider | None = None,
    sessions_dir: str = DEFAULT_SESSIONS_DIR,
) -> dict:
    """Deferred provider capture for a session, run by the watcher at process time.

    Reads the window bounds from <sessions_dir>/<id>/session.json (written by start/stop)
    and writes transcript.json from the provider's entries in that window. By the time the
    watcher runs this (the recording has been exported, minutes after stop), a flush-prone
    provider has certainly flushed by then. Idempotent: if transcript.json already exists,
    it is left as-is.
    """
    session_dir = homebase / sessions_dir / session_id
    transcript_path = session_dir / "transcript.json"
    if transcript_path.exists():
        return {"session_id": session_id, "entry_count": None, "transcript_path": str(transcript_path), "skipped": True}

    meta_path = _session_meta_path(homebase, session_id, sessions_dir)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"session_id": session_id, "entry_count": 0, "transcript_path": None, "error": "no session.json"}

    start_epoch = float(meta.get("start_epoch", 0.0))
    # If stop was never recorded, treat the window as open-ended up to now.
    stop_epoch = float(meta["stop_epoch"]) if "stop_epoch" in meta else datetime.now().astimezone().timestamp()

    active_provider = provider or get_provider(session_dir=session_dir)
    entries = active_provider.entries_in_window(
        start_epoch, stop_epoch, tolerance_s=START_TOLERANCE_S, grace_s=FLUSH_GRACE_S)
    transcript = build_transcript(entries)
    if transcript:
        session_dir.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(json.dumps(transcript, indent=2) + "\n", encoding="utf-8")
    return {
        "session_id": session_id,
        "entry_count": transcript["entry_count"] if transcript else 0,
        "transcript_path": str(transcript_path) if transcript else None,
    }


def cli() -> None:
    parser = argparse.ArgumentParser(description="homebase recording session markers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_start = sub.add_parser("start", help="begin a recording session")
    p_start.add_argument("--slug", default=None, help="short name appended to the session id")
    p_start.add_argument("--homebase", type=Path, default=DEFAULT_HOMEBASE)
    p_start.add_argument("--sessions-dir", default=DEFAULT_SESSIONS_DIR,
                         help="repo-relative folder to record into (default: recordings)")

    p_stop = sub.add_parser("stop", help="capture the narration for the active session")
    p_stop.add_argument("--homebase", type=Path, default=DEFAULT_HOMEBASE)
    p_stop.add_argument("--provider", default=None,
                        help="dictation provider override: vowen|wisprflow|file "
                             "(default: $DICTATION_PROVIDER or file)")
    p_stop.add_argument("--sessions-dir", default=DEFAULT_SESSIONS_DIR,
                        help="repo-relative folder of the active session (default: recordings)")

    p_cap = sub.add_parser("capture", help="deferred narration capture for a session (used by the watcher)")
    p_cap.add_argument("--session", required=True, help="session id to capture")
    p_cap.add_argument("--homebase", type=Path, default=DEFAULT_HOMEBASE)
    p_cap.add_argument("--provider", default=None,
                       help="dictation provider override: vowen|wisprflow|file")
    p_cap.add_argument("--sessions-dir", default=DEFAULT_SESSIONS_DIR,
                       help="repo-relative folder of the session (default: recordings)")

    args = parser.parse_args()

    if args.cmd == "start":
        session_id = start_session(args.homebase, slug=args.slug, sessions_dir=args.sessions_dir)
        target = args.homebase / args.sessions_dir / session_id / "raw.mp4"
        print(f"> recording session started: {session_id}")
        print("  record with your screen recorder and narrate with your dictation provider")
        print("  when done:  python3 record_session.py stop")
        print(f"  then export your recording to:  {target}")
        return

    if args.cmd == "capture":
        session_dir = args.homebase / args.sessions_dir / args.session
        provider = get_provider(args.provider, session_dir=session_dir)
        result = capture_session(args.homebase, args.session, provider, args.sessions_dir)
        if result.get("skipped"):
            print(f"= transcript already present for {args.session}")
        elif result["entry_count"]:
            print(f"* captured {result['entry_count']} narration entr(ies) -> {result['transcript_path']}")
        else:
            print(f"* no narration found in window for {args.session}", file=sys.stderr)
        return

    # stop
    session_id_probe = None
    try:
        marker = json.loads(marker_path(args.homebase, args.sessions_dir).read_text(encoding="utf-8"))
        session_id_probe = marker.get("session_id")
    except (OSError, json.JSONDecodeError):
        pass
    session_dir = (args.homebase / args.sessions_dir / session_id_probe) if session_id_probe else None
    provider = get_provider(args.provider, session_dir=session_dir)
    try:
        result = stop_session(args.homebase, provider, sessions_dir=args.sessions_dir)
    except NoActiveSession as e:
        print(f"x {e}", file=sys.stderr)
        sys.exit(1)

    if result["entry_count"]:
        print(f"* captured {result['entry_count']} narration entr(ies) -> {result['transcript_path']}")
    else:
        print("* stopped. Narration not flushed yet -- the watcher will capture it when you export.")
    print(f"  export your recording to:  {result['raw_target']}")


if __name__ == "__main__":
    cli()
