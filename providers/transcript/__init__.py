"""Factory for the TranscriptProvider seam. See provider.py for the interface."""

from __future__ import annotations

import os
from pathlib import Path

from providers.transcript.file import FileProvider
from providers.transcript.provider import (
    HealthIssue,
    ProviderHealth,
    TranscriptEntry,
    TranscriptProvider,
)
from providers.transcript.vowen import VowenProvider
from providers.transcript.wisprflow import WisprFlowProvider

_PROVIDERS = ("vowen", "wisprflow", "file")


def get_provider(name: str | None = None, *, session_dir: Path | None = None) -> TranscriptProvider:
    """Build the configured TranscriptProvider.

    `name` defaults to the DICTATION_PROVIDER env var, then "file". `session_dir` is only
    used by FileProvider (its transcript.json lives per-session); other adapters ignore it.
    """
    chosen = (name or os.environ.get("DICTATION_PROVIDER") or "file").strip().lower()
    if chosen == "vowen":
        return VowenProvider()
    if chosen == "wisprflow":
        return WisprFlowProvider()
    if chosen == "file":
        return FileProvider(session_dir=session_dir)
    raise ValueError(f"unknown DICTATION_PROVIDER: {chosen!r} (expected one of {_PROVIDERS})")


__all__ = [
    "FileProvider",
    "HealthIssue",
    "ProviderHealth",
    "TranscriptEntry",
    "TranscriptProvider",
    "VowenProvider",
    "WisprFlowProvider",
    "get_provider",
]
