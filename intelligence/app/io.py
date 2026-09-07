"""Filesystem helpers. Atomic writes, slug normalization, repo path resolution."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path

_SLUG_INVALID = re.compile(r"[^a-z0-9\-]+")
_SLUG_COLLAPSE = re.compile(r"-{2,}")


def slugify(value: str) -> str:
    """Convert any string to a safe kebab-case slug.

    Rules: ascii-lower, replace non [a-z0-9-] with hyphens, collapse repeats, strip ends.
    Empty input returns "untitled".
    """
    if not value:
        return "untitled"

    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower().strip()
    hyphenated = _SLUG_INVALID.sub("-", ascii_only)
    collapsed = _SLUG_COLLAPSE.sub("-", hyphenated).strip("-")
    return collapsed or "untitled"


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically. Creates parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_append(path: Path, content: str) -> None:
    """Append content to path. Read-modify-write under a temp file for atomicity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    atomic_write(path, existing + content)


def session_paths(homebase_root: Path, session_id: str) -> dict[str, Path]:
    """Standard output paths for a session, derived from homebase_root."""
    return {
        "recording_dir": homebase_root / "recordings" / session_id,
        "workflow_map": homebase_root / "recordings" / session_id / "workflow-map.md",
        "prd": homebase_root / "prds" / session_id / "PRD.md",
        "handoff": homebase_root / "prds" / session_id / "handoff-prompt.md",
    }


def library_path(homebase_root: Path, deal_type: str, sub_type: str, intent_slug: str) -> Path:
    """Compute the dynamic library path. Slugifies every segment.

    CRITICAL: this function is the only place the library path is derived.
    Never construct library paths by string concatenation elsewhere.
    """
    parts = [slugify(deal_type), slugify(sub_type), slugify(intent_slug)]
    return homebase_root / "workflows" / "library" / parts[0] / parts[1] / parts[2]
