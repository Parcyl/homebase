"""WisprFlowProvider: BEST-EFFORT, unverified. Read this whole docstring before relying on it.

WisprFlow's real on-disk store is NOT a flat JSON history file the way some other dictation
tools' adapters read. Research done while building this adapter (2026-09-06, against an
installed-but-dormant WisprFlow on the build machine):
  - `~/Library/Application Support/Wispr Flow/` holds `config.json` (app settings/notification
    state only -- NOT transcript entries; it does contain a `lastTranscriptTimestamp`-shaped
    key but not the transcripts themselves) and an Electron `Local Storage/` leveldb store.
  - The app's own log file records lines like `Database backup was successful! .../Wispr
    Flow/backups/backup-<timestamp>.sqlite`, confirming the PRIMARY local store is a SQLite
    database, not JSON. No live `.sqlite` file or `backups/` directory was present to inspect
    on the build machine, so the table/column schema could NOT be confirmed.
  - Community/vendor docs describe optional cloud sync (a Supabase-backed account), which
    means some or all history may not be fully local at all.

None of that adds up to a confirmed, stable schema this adapter can read directly, and this
adapter does NOT attempt to open WisprFlow's internal SQLite database -- guessing a schema
for someone else's app database is worse than declining to support it. Do NOT extend this
file to read `flow.sqlite` (or similar) without first confirming the real schema against a
live install.

What this adapter DOES do: read a JSON file at a path YOU configure (`WISPRFLOW_HISTORY_PATH`),
in one of two shapes (auto-detected), so a user who exports or scripts their own dump of
WisprFlow history has somewhere to point it:
  - timestamp-shaped: a list of `{"timestamp": <ISO-8601>, "text": <str>}` (newest-first or
    not -- both are handled), OR
  - File-provider-shaped: a list of `{"epoch"|"ts": ..., "text": <str>}`.
  - Either may be wrapped in `{"history": [...]}` or `{"entries": [...]}`.

If your WisprFlow history genuinely lives in SQLite and you want a real adapter, export it to
one of the shapes above (or send a PR with a confirmed schema).
"""

from __future__ import annotations

import datetime
import json
import os
import time
from pathlib import Path
from typing import Callable

from providers.transcript.provider import HealthIssue, ProviderHealth, TranscriptEntry

DEFAULT_HISTORY_PATH_ENV = "WISPRFLOW_HISTORY_PATH"


def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _entry_epoch_and_iso(raw: dict) -> tuple[float | None, str]:
    """Accept either the timestamp-shaped {"timestamp": iso} or File's {"epoch"|"ts": ...} shape."""
    for key in ("timestamp", "ts"):
        ts = raw.get(key)
        if isinstance(ts, str):
            parsed = _parse_ts(ts)
            if parsed is not None:
                return parsed.timestamp(), ts
    if "epoch" in raw:
        try:
            epoch = float(raw["epoch"])
            iso = datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).isoformat()
            return epoch, iso
        except (TypeError, ValueError):
            pass
    return None, ""


def _read_entries(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("history") or data.get("entries") or []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


class WisprFlowProvider:
    """Best-effort adapter for a user-configured WisprFlow history export. See module
    docstring: the schema is NOT confirmed against a real WisprFlow database."""

    name = "wisprflow"

    def __init__(
        self,
        *,
        history_path: Path | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        configured = os.environ.get(DEFAULT_HISTORY_PATH_ENV)
        self.history_path = history_path or (Path(configured) if configured else None)
        self._now = now_fn

    def entries_in_window(
        self,
        start_epoch: float,
        stop_epoch: float | None,
        tolerance_s: float = 60,
        grace_s: float = 90,
    ) -> list[TranscriptEntry]:
        if self.history_path is None:
            return []
        lo = start_epoch - tolerance_s
        hi = None if stop_epoch is None else stop_epoch + grace_s

        selected: list[tuple[float, TranscriptEntry]] = []
        for raw in _read_entries(self.history_path):
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            epoch, iso = _entry_epoch_and_iso(raw)
            if epoch is None:
                continue  # unlike FileProvider, an unconfirmed schema gets no benefit of the doubt
            if epoch < lo or (hi is not None and epoch > hi):
                continue
            selected.append((epoch, TranscriptEntry(epoch=epoch, ts_iso=iso, text=text,
                                                      source=self.name)))
        selected.sort(key=lambda pair: pair[0])
        return [entry for _, entry in selected]

    def health(self) -> ProviderHealth:
        if self.history_path is None:
            issue = HealthIssue(
                "wisprflow_history_configured", False, hard=False,
                message=f"{DEFAULT_HISTORY_PATH_ENV} is not set -- best-effort adapter, "
                        "see providers/transcript/wisprflow.py",
            )
            return ProviderHealth(
                # hard=False everywhere in this adapter (never confirmed enough to block a
                # session on), so "healthy" per the not-any-blocking contract is True even
                # though nothing is configured -- the message + issue carry the real signal.
                name=self.name, healthy=not issue.blocking, running=None,
                last_entry_age_s=None, issues=[issue],
                message="WisprFlow adapter is unconfigured (best-effort, unverified schema)",
            )
        entries = _read_entries(self.history_path)
        readable = HealthIssue("wisprflow_history_readable", bool(entries), hard=False,
                                message="" if entries else "configured file has no entries")
        newest = max((_entry_epoch_and_iso(e)[0] or 0.0 for e in entries), default=None)
        age = (self._now() - newest) if newest else None
        return ProviderHealth(
            name=self.name, healthy=True, running=None, last_entry_age_s=age,
            issues=[readable],
            message="best-effort: schema is unverified, see providers/transcript/wisprflow.py",
        )
