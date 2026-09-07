"""ScreenStudioRecorder: control + master-resolution for Screen Studio. macOS only.

Screen Studio holds recordings in-app as `~/Documents/Screen Studio/<name>.screenstudio`
bundles until you export one by hand -- the pipeline used to require that manual export
before it could run at all (a real gap the source project hit). This adapter closes it two
ways: `start`/`stop` drive Screen Studio's configured keyboard shortcut via AppleScript (it
has no rich scriptable API of its own), and `resolve_master` finds the bundle whose
recording start is closest to the session's start time and hands back its master mp4 --
`pipeline/doc_generator.py` then adopts that file into the session as raw.mp4 (see
resolve_recording there), no manual export required.

Absorbs `SCREEN_STUDIO_DIR` / `find_screenstudio_master` from the source project's
session-capture processor and the AppleScript start/stop keystrokes from its menu-bar
recorder scripts.

macOS only: `start`/`stop` shell out to `osascript`; `resolve_master` just reads a folder
and works on any platform where that folder happens to exist, but there is nothing to
point it at on a non-Mac.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable

_HERE = Path(__file__).resolve().parent

DEFAULT_SCREEN_STUDIO_DIR = Path(os.environ.get(
    "SCREEN_STUDIO_DIR", str(Path.home() / "Documents" / "Screen Studio")))
# A Screen Studio bundle's recording start ~= the session's start, within this many
# seconds; outside it, never adopt a video that might belong to a different session.
DEFAULT_MATCH_TOLERANCE_S = float(os.environ.get("SCREEN_STUDIO_MATCH_TOLERANCE_S", "1800"))  # 30 min

START_SCRIPT = _HERE / "screen_studio_start.applescript"
STOP_SCRIPT = _HERE / "screen_studio_stop.applescript"


def _bundle_start_time(master: Path) -> float:
    """Recording start ~= the master file's creation time. Falls back to mtime where
    birthtime is unavailable (mtime is the recording END, so only a last resort)."""
    try:
        st = master.stat()
        return getattr(st, "st_birthtime", None) or st.st_mtime
    except OSError:
        return 0.0


def find_screenstudio_master(
    start_epoch: float,
    *,
    ss_dir: Path = DEFAULT_SCREEN_STUDIO_DIR,
    tolerance_s: float = DEFAULT_MATCH_TOLERANCE_S,
    time_fn: Callable[[Path], float] = _bundle_start_time,
) -> Path | None:
    """The Screen Studio master mp4 whose recording start is closest to session start,
    within tolerance. Returns None if nothing matches (never adopt the wrong video)."""
    if start_epoch <= 0 or not ss_dir.exists():
        return None
    best: Path | None = None
    best_delta = tolerance_s
    for bundle in ss_dir.glob("*.screenstudio"):
        master = bundle / "recording" / "channel-1-display-0.mp4"
        if not master.exists():
            mp4s = sorted((p for p in bundle.rglob("*.mp4") if p.is_file()),
                          key=lambda p: p.stat().st_size, reverse=True)
            if not mp4s:
                continue
            master = mp4s[0]
        delta = abs(time_fn(master) - start_epoch)
        if delta <= best_delta:
            best_delta = delta
            best = master
    return best


def _run_osascript(script: Path) -> None:
    try:
        subprocess.run(["osascript", str(script)], capture_output=True, timeout=10, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass  # best-effort: a stuck/missing osascript must never crash the session flow


class ScreenStudioRecorder:
    """Drives Screen Studio via AppleScript keystrokes. macOS only.

    `runner` is injectable so tests never need a real Screen Studio install or osascript.
    """

    name = "screen-studio"

    def __init__(
        self,
        *,
        ss_dir: Path | None = None,
        tolerance_s: float | None = None,
        runner: Callable[[Path], None] = _run_osascript,
    ) -> None:
        self.ss_dir = ss_dir or DEFAULT_SCREEN_STUDIO_DIR
        self.tolerance_s = DEFAULT_MATCH_TOLERANCE_S if tolerance_s is None else tolerance_s
        self._run = runner

    def start(self, session_dir: Path) -> None:
        self._run(START_SCRIPT)

    def stop(self, session_dir: Path) -> None:
        self._run(STOP_SCRIPT)

    def resolve_master(self, session_start_epoch: float, session_dir: Path) -> Path | None:
        return find_screenstudio_master(
            session_start_epoch, ss_dir=self.ss_dir, tolerance_s=self.tolerance_s)
