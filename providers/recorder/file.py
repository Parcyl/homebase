"""FileRecorder: the default, bring-your-own recorder adapter. No GUI control.

No process to start or stop -- the operator uses whatever screen recorder they like and
drops the exported video into `<session_dir>/`. `resolve_master` looks for it there: an
existing `raw.mp4` wins, otherwise the largest `*.mp4` in the folder is adopted (screen
recorders routinely export under their own name, e.g. Screen Studio's "Area.mp4", so
requiring the exact filename would mean a manual rename every session).
"""

from __future__ import annotations

from pathlib import Path


class FileRecorder:
    """No-op start/stop; resolves whatever mp4 the operator drops in session_dir."""

    name = "file"

    def start(self, session_dir: Path) -> None:
        pass  # nothing to control -- the operator runs their own recorder

    def stop(self, session_dir: Path) -> None:
        pass

    def resolve_master(self, session_start_epoch: float, session_dir: Path) -> Path | None:
        raw = session_dir / "raw.mp4"
        if raw.exists():
            return raw
        mp4s = [p for p in session_dir.glob("*.mp4") if p.is_file()]
        if not mp4s:
            return None
        return max(mp4s, key=lambda p: p.stat().st_size)
