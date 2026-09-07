"""FileProvider: the default, bring-your-own dictation adapter. Zero tool assumptions.

No background tool, no history file, no process to watch -- the operator drops narration
into `<session_dir>/transcript.json` themselves (from any dictation tool, a manual note, or
a transcription service run by hand) and this adapter reads it.

Schema (a JSON array; each entry is one spoken/typed chunk):
    [
      {"epoch": 1782623547.0, "text": "first part"},
      {"ts": "2026-06-01T20:31:00Z", "text": "second part"},
      {"text": "no timestamp -- always included, can't be windowed"}
    ]

`epoch` (unix seconds, float) or `ts` (ISO-8601 string) may be given; if both are present
`epoch` wins. An entry with neither is always included in `entries_in_window` -- since the
file already lives inside one session's folder, an untimed entry is trusted to belong to
that session rather than dropped for lacking a timestamp we never asked for.

Because `entries_in_window` is called with a `session_dir`-scoped path per instance (see
FileProvider.__init__), a single instance is bound to one session -- construct a fresh one
per session, e.g. `FileProvider(session_dir=session_dir)`.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

from providers.transcript.provider import HealthIssue, ProviderHealth, TranscriptEntry

TRANSCRIPT_FILENAME = "transcript.json"


def _parse_ts(ts: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _entry_epoch_and_iso(raw: dict) -> tuple[float | None, str]:
    if "epoch" in raw:
        try:
            epoch = float(raw["epoch"])
        except (TypeError, ValueError):
            epoch = None
        if epoch is not None:
            iso = raw.get("ts")
            if not isinstance(iso, str):
                iso = datetime.datetime.fromtimestamp(
                    epoch, tz=datetime.timezone.utc).isoformat()
            return epoch, iso
    ts = raw.get("ts")
    if isinstance(ts, str):
        parsed = _parse_ts(ts)
        if parsed is not None:
            return parsed.timestamp(), ts
        return None, ts
    return None, ""


def _read_entries(path: Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in data if isinstance(e, dict)]


class FileProvider:
    """Reads `<session_dir>/transcript.json`. One instance per session."""

    name = "file"

    def __init__(self, *, session_dir: Path | None = None) -> None:
        self.session_dir = session_dir

    def _path(self) -> Path | None:
        return (self.session_dir / TRANSCRIPT_FILENAME) if self.session_dir else None

    def entries_in_window(
        self,
        start_epoch: float,
        stop_epoch: float | None,
        tolerance_s: float = 60,
        grace_s: float = 90,
    ) -> list[TranscriptEntry]:
        path = self._path()
        if path is None:
            return []
        lo = start_epoch - tolerance_s
        hi = None if stop_epoch is None else stop_epoch + grace_s

        selected: list[TranscriptEntry] = []
        for raw in _read_entries(path):
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            epoch, iso = _entry_epoch_and_iso(raw)
            if epoch is None:
                # No usable timestamp -- can't window it, trust it belongs to this session.
                selected.append(TranscriptEntry(epoch=0.0, ts_iso=iso, text=text, source=self.name))
                continue
            if epoch < lo or (hi is not None and epoch > hi):
                continue
            selected.append(TranscriptEntry(epoch=epoch, ts_iso=iso, text=text, source=self.name))
        return selected

    def health(self) -> ProviderHealth:
        # No background tool and no session-independent file to check -- this provider is
        # "healthy" by construction; the operator either drops the file or doesn't, and
        # that's discovered when the pipeline reads it, not by a standing readiness probe.
        return ProviderHealth(
            name=self.name, healthy=True, running=None, last_entry_age_s=None,
            issues=[HealthIssue("file_provider", True, hard=False,
                                 message="bring your own transcript.json per session")],
            message="file provider: nothing to check globally",
        )
