"""RecorderAdapter: the pipeline never talks to a screen recorder directly.

The pipeline only ever tells a recorder to start or stop, and separately asks it to
resolve the master video file for a session -- wherever that recorder happens to keep it
until it's adopted into `<session_dir>/raw.mp4` (see pipeline/doc_generator.py's
resolve_recording). A new recorder is a new adapter module in providers/recorder/, never a
change to the pipeline.

Adapters shipped: ScreenStudioRecorder (macOS, AppleScript-driven) and FileRecorder (the
default -- bring your own mp4, dropped by hand into the session dir). Selected via
providers.recorder.get_recorder(), driven by the RECORDER env var.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class RecorderAdapter(Protocol):
    """Starts/stops a screen recording and resolves its master file for a session."""

    name: str

    def start(self, session_dir: Path) -> None:
        """Begin recording. Best-effort: a recorder with no scriptable API may only be
        able to bring the app forward and send its configured shortcut (see
        screen_studio.py); a bring-your-own recorder has nothing to do here at all."""
        ...

    def stop(self, session_dir: Path) -> None:
        """Stop recording. Best-effort, mirrors start()."""
        ...

    def resolve_master(self, session_start_epoch: float, session_dir: Path) -> Path | None:
        """The master video for this session, wherever the recorder currently keeps it.

        Already inside session_dir for a bring-your-own recorder (the operator dropped it
        there), or elsewhere entirely (e.g. a Screen Studio bundle under
        ~/Documents/Screen Studio) for one located by matching session_start_epoch against
        the recorder's own store. Returns None if nothing has landed yet -- callers must
        never adopt a guess.
        """
        ...
