#!/usr/bin/env python3
"""launchd-triggered mic backup recorder.

Runs under the user's launchd (its own TCC identity, in the GUI session) instead of as a
child of a menu-bar app -- a menu-bar app with no Microphone permission would spawn an
avfoundation stream that records silence. A dedicated launchd agent gets its OWN Microphone
entry that can be granted once, so the recording actually captures sound.

The Start action kickstarts this agent; it records the active session's mic to
backup-audio.wav (with the RMS silence guard in capture_audio_backup), then self-finalizes
when the session marker clears at Stop. Owning both start and stop also avoids the bug
class where Stop leaves ffmpeg running.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import capture_audio_backup as cab  # noqa: E402
from record_session import DEFAULT_SESSIONS_DIR, marker_path  # noqa: E402

HOMEBASE = Path(os.environ.get("HOMEBASE_ROOT", str(HERE.parent)))
SESSIONS_DIR = os.environ.get("BACKUP_SESSIONS_DIR", DEFAULT_SESSIONS_DIR)
POLL_S = 3.0
MAX_RUNTIME_S = float(os.environ.get("BACKUP_MAX_S", "10800"))  # 3h safety cap


def active_session_id() -> str | None:
    marker = marker_path(HOMEBASE, SESSIONS_DIR)
    try:
        return json.loads(marker.read_text(encoding="utf-8")).get("session_id") or None
    except (OSError, json.JSONDecodeError, AttributeError):
        return None


def _notify(msg: str) -> None:
    os.system("osascript -e 'display notification \"%s\" with title \"homebase\"' 2>/dev/null"
              % msg.replace('"', "'")[:170])


def main() -> int:
    sid = active_session_id()
    if not sid:
        return 0  # nothing active; benign no-op
    session_dir = HOMEBASE / SESSIONS_DIR / sid

    r = cab.start_backup(session_dir)
    if not r.get("ok"):
        reason = r.get("reason", "unknown")
        (session_dir / ".capture-alert").write_text(
            f"backup audio FAILED: {reason}\n", encoding="utf-8")
        _notify(f"Backup audio FAILED: {reason}")
        return 1

    started = time.time()
    while time.time() - started < MAX_RUNTIME_S:
        if active_session_id() != sid:  # Stop cleared the marker
            break
        time.sleep(POLL_S)
    cab.stop_backup(session_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
