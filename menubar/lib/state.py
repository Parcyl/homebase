"""Read-only helpers the SwiftBar plugin uses every refresh.

Pure stdlib. No third-party imports. No exceptions escape these functions; every
helper returns a safe default so the menu bar never goes blank.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

# menubar/lib/state.py -> menubar/lib -> menubar -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]


def homebase_root() -> Path:
    return Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT)))


@dataclass
class StateView:
    stage: str = "unknown"
    session_id: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    last_prd: str | None = None
    last_handoff: str | None = None
    message: str | None = None
    error: str | None = None
    readable: bool = True
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_processing(self) -> bool:
        return self.stage in {
            "recording",
            "ready",
            "transcribing",
            "classifying",
            "extracting",
            "grounding",
            "comparing",
            "generating",
            "filing",
        }

    @property
    def is_error(self) -> bool:
        return self.stage == "error"

    @property
    def is_idle_or_done(self) -> bool:
        return self.stage in {"idle", "complete"}


def read_state(root: Path | None = None) -> StateView:
    """Reads agents/pipeline-state.json, the single state contract documented in
    intelligence/app/pipeline_state.py -- pipeline/, intelligence/, and this plugin all
    read or write through that one file.
    """
    root = root or homebase_root()
    path = root / "agents" / "pipeline-state.json"
    if not path.exists():
        return StateView(stage="unknown", readable=False)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return StateView(stage="unknown", readable=False)
    if not isinstance(payload, dict):
        return StateView(stage="unknown", readable=False)
    return StateView(
        stage=str(payload.get("stage", "unknown")),
        session_id=payload.get("session_id"),
        started_at=payload.get("started_at"),
        updated_at=payload.get("updated_at"),
        last_prd=payload.get("last_prd"),
        last_handoff=payload.get("last_handoff"),
        message=payload.get("message"),
        error=payload.get("error"),
        readable=True,
        raw=payload,
    )


def recent_log_lines(root: Path | None = None, n: int = 5) -> list[str]:
    """Tails an optional operator-maintained activity feed.

    Nothing in this repo writes agents/activity-log.md by default -- it is a bring-your-own
    feed, the same philosophy as providers/transcript/file.py and providers/recorder/file.py:
    if you wire something up to append "- [...]" lines here (a launchd watcher, a git hook,
    whatever), the dropdown will show them. Absent, this returns [] and the dropdown says
    "no log entries yet", never an error.
    """
    root = root or homebase_root()
    path = root / "agents" / "activity-log.md"
    if not path.exists():
        return []
    try:
        lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return []
    only_entries = [ln for ln in lines if ln.startswith("- [")]
    return list(reversed(only_entries[-n:]))


def health_ok(url: str = "http://127.0.0.1:8080/health", timeout: float = 0.5) -> bool:
    """Checks the intelligence spine's /health endpoint (see intelligence/app/main.py)."""
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310
            return resp.status == 200
    except (URLError, TimeoutError, socket.timeout, OSError):
        return False


def latest_prd_path(root: Path | None = None) -> Path | None:
    """Newest prds/<session_id>/PRD.md, written by intelligence/app/io.py."""
    root = root or homebase_root()
    prds = root / "prds"
    if not prds.exists():
        return None
    candidates = sorted(prds.rglob("PRD.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def latest_handoff_path(root: Path | None = None) -> Path | None:
    """Newest prds/<session_id>/handoff-prompt.md, written by intelligence/app/io.py."""
    root = root or homebase_root()
    prds = root / "prds"
    if not prds.exists():
        return None
    candidates = sorted(
        prds.rglob("handoff-prompt.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def latest_digest_path(root: Path | None = None) -> Path | None:
    """Newest recordings/<session_id>/DIGEST.md, written by pipeline/doc_generator.py."""
    root = root or homebase_root()
    sessions = root / "recordings"
    if not sessions.exists():
        return None
    candidates = sorted(
        sessions.rglob("DIGEST.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return candidates[0] if candidates else None


def capture_alert(root: Path | None = None, *, check_last: int = 3) -> str | None:
    """First line of the newest session's .capture-alert, if any.

    Written by pipeline/capture_liveness_monitor.py when the configured dictation provider
    stops capturing, and by pipeline/doc_generator.py when a session never got a recording.
    Surfacing it here turns the menu red during a live capture failure.
    """
    base = homebase_root() if root is None else root
    base = base / "recordings"
    try:
        sessions = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    except OSError:
        return None
    for session in sessions[:check_last]:
        alert = session / ".capture-alert"
        try:
            if alert.exists():
                return alert.read_text(encoding="utf-8").strip().splitlines()[0][:80]
        except OSError:
            continue
    return None
