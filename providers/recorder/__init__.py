"""Factory for the RecorderAdapter seam. See adapter.py for the interface."""

from __future__ import annotations

import os

from providers.recorder.adapter import RecorderAdapter
from providers.recorder.file import FileRecorder
from providers.recorder.screen_studio import ScreenStudioRecorder

_RECORDERS = ("screen-studio", "file")


def get_recorder(name: str | None = None) -> RecorderAdapter:
    """Build the configured RecorderAdapter.

    `name` defaults to the RECORDER env var, then "file".
    """
    chosen = (name or os.environ.get("RECORDER") or "file").strip().lower()
    if chosen == "screen-studio":
        return ScreenStudioRecorder()
    if chosen == "file":
        return FileRecorder()
    raise ValueError(f"unknown RECORDER: {chosen!r} (expected one of {_RECORDERS})")


__all__ = [
    "FileRecorder",
    "RecorderAdapter",
    "ScreenStudioRecorder",
    "get_recorder",
]
