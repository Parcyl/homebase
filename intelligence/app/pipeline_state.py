"""Pipeline state contract.

A single JSON file at HOMEBASE_ROOT/agents/pipeline-state.json is the source of
truth for the live pipeline stage. Recording scripts, LangGraph nodes, n8n,
and the menu bar all read or write through this contract.

Writes are atomic (tmp + rename + fsync). Reads tolerate a missing file
and return safe defaults.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .io import atomic_write
from .settings import get_settings

VALID_STAGES = frozenset(
    {
        "idle",
        "recording",
        "ready",
        "transcribing",
        "classifying",
        "extracting",
        "grounding",
        "comparing",
        "generating",
        "filing",
        "complete",
        "error",
    }
)


def state_path(homebase_root: Path | None = None) -> Path:
    root = homebase_root or get_settings().homebase_root
    return root / "agents" / "pipeline-state.json"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(homebase_root: Path | None = None) -> dict[str, Any]:
    """Return current state. Safe defaults on missing or malformed file."""
    path = state_path(homebase_root)
    if not path.exists():
        return _default()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return _default()
        return payload
    except (OSError, json.JSONDecodeError):
        return _default()


def _default() -> dict[str, Any]:
    return {
        "stage": "idle",
        "session_id": None,
        "started_at": None,
        "updated_at": _now(),
        "last_prd": None,
        "last_handoff": None,
        "message": None,
        "error": None,
    }


def update(
    stage: str,
    session_id: str | None = None,
    *,
    homebase_root: Path | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Merge stage and any extras into the state file. Atomic write."""
    if stage not in VALID_STAGES:
        raise ValueError(f"invalid stage {stage!r}, must be one of {sorted(VALID_STAGES)}")

    current = read(homebase_root)
    now = _now()

    if stage == "recording" and current.get("stage") != "recording":
        current["started_at"] = now
    if stage == "idle":
        current["started_at"] = None
        current["error"] = None

    current["stage"] = stage
    if session_id is not None:
        current["session_id"] = session_id
    current["updated_at"] = now
    if stage != "error":
        current["error"] = current.get("error") if stage in {"recording", "ready"} else None
    for key, value in extra.items():
        current[key] = value

    atomic_write(state_path(homebase_root), json.dumps(current, indent=2) + "\n")
    return current
