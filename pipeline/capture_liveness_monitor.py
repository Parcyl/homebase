#!/usr/bin/env python3
"""During-record capture liveness monitor (the real guard).

Spawned when a session begins; exits when the session's start marker is cleared (Stop) or
the session folder disappears. While running it polls the configured TranscriptProvider's
`health()` and:

  1. FIRST-ENTRY grace: if no entry newer than session start appears within
     FIRST_ENTRY_GRACE_S, fire a LOUD, visible alert -- the dictation provider is not
     capturing. Stop and restart it.
  2. STALL detection: after the first entry, if the newest entry stops advancing for
     STALL_S, alert again -- the provider froze mid-session.

This deliberately watches an ARTIFACT (the age of the provider's newest entry, from
`ProviderHealth.last_entry_age_s`), not a PROCESS. A dictation tool's process can stay
alive while its capture is internally dead, so "is it running" proves nothing -- see
providers/transcript/vowen.py for the incident this guards against.

Alerts are visible (macOS notification) AND written to a `.capture-alert` sentinel in the
session folder. An alert nobody sees is useless; this one is loud on purpose.

Usage: capture_liveness_monitor.py --session <id> [--homebase <path>] [--sessions-dir <dir>]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from providers.transcript import TranscriptProvider, get_provider  # noqa: E402
from record_session import DEFAULT_SESSIONS_DIR, marker_path  # noqa: E402

POLL_S = 5.0
FIRST_ENTRY_GRACE_S = float(os.environ.get("CAPTURE_FIRST_ENTRY_GRACE_S", "90"))
STALL_S = float(os.environ.get("CAPTURE_STALL_S", "45"))


def assess(*, seconds_since_start: float, last_entry_age_s: float | None) -> tuple[bool, str]:
    """Pure decision: should we alert, and with what message.

    `last_entry_age_s` (from ProviderHealth, see providers/transcript/provider.py) is the
    age of the newest entry the provider can currently see across its WHOLE history, not
    scoped to this session. An age greater than `seconds_since_start` means that entry
    predates the session start (nothing new has landed yet); an age less than or equal to
    it means an entry landed during the session. This lets a single artifact-freshness
    number drive both the first-entry grace and the mid-session stall check.

    Drives the loop so it can be unit-tested with no live provider.
    """
    if last_entry_age_s is None or last_entry_age_s > seconds_since_start:
        if seconds_since_start >= FIRST_ENTRY_GRACE_S:
            return True, (f"Nothing captured {int(seconds_since_start)}s into the session. "
                          f"The dictation provider is frozen. Stop, restart it, start over.")
        return False, ""
    if last_entry_age_s >= STALL_S:
        return True, (f"Capture stopped {int(last_entry_age_s)}s ago (mid-session freeze). "
                      f"Check the dictation provider.")
    return False, ""


def notify(title: str, message: str) -> None:
    """Visible macOS notification. Best-effort."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {json.dumps(message)} with title {json.dumps(title)} sound name "Basso"'],
            timeout=5, check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


def session_active(homebase: Path, session_id: str, sessions_dir: str = DEFAULT_SESSIONS_DIR) -> bool:
    marker = marker_path(homebase, sessions_dir)
    if not marker.exists():
        return False
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("session_id") == session_id
    except (OSError, json.JSONDecodeError):
        return False


def monitor(
    homebase: Path,
    session_id: str,
    *,
    sessions_dir: str = DEFAULT_SESSIONS_DIR,
    provider: TranscriptProvider | None = None,
    poll_s: float = POLL_S,
    sleep=time.sleep,
) -> int:
    session_dir = homebase / sessions_dir / session_id
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    start_epoch = float(meta["start_epoch"])
    alert_file = session_dir / ".capture-alert"
    active_provider = provider or get_provider(session_dir=session_dir)

    # "landed" (has any entry arrived since start) is monotonic: once True it stays True
    # for the rest of the session, since it only asks whether the FIRST entry has arrived,
    # not whether narration is still flowing. It splits the loop into the two phases the
    # original guard watched for: waiting for a first entry, then watching for a stall.
    fired: set[str] = set()

    while session_active(homebase, session_id, sessions_dir):
        now = time.time()
        seconds_since_start = now - start_epoch
        health = active_provider.health()
        alert, message = assess(seconds_since_start=seconds_since_start,
                                last_entry_age_s=health.last_entry_age_s)
        landed = health.last_entry_age_s is not None and health.last_entry_age_s <= seconds_since_start
        key = "stall" if landed else "first"

        if alert and key not in fired:
            fired.add(key)
            alert_file.write_text(message + "\n", encoding="utf-8")
            notify("Capture problem", message)
            print(f"LIVENESS ALERT: {message}", flush=True)
        elif not alert and key in fired:
            # Recovered (a fresh entry landed after a stall alert) -- clear the sentinel.
            fired.discard(key)
            alert_file.unlink(missing_ok=True)
        sleep(poll_s)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture liveness monitor")
    ap.add_argument("--session", required=True)
    ap.add_argument("--homebase", type=Path,
                    default=Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT))))
    ap.add_argument("--sessions-dir", default=DEFAULT_SESSIONS_DIR)
    ap.add_argument("--provider", default=None,
                    help="dictation provider override: vowen|wisprflow|file")
    args = ap.parse_args()
    session_dir = args.homebase / args.sessions_dir / args.session
    provider = get_provider(args.provider, session_dir=session_dir)
    try:
        return monitor(args.homebase, args.session, sessions_dir=args.sessions_dir,
                       provider=provider)
    except (OSError, KeyError, json.JSONDecodeError) as e:
        print(f"liveness monitor error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
