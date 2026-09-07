"""VowenProvider: narration from Vowen's local transcription history.

Absorbs the Vowen-specific logic that used to live directly in record_session.py
(`_select_window` / `vowen_entries_in_window`, source lines ~154-206) and
capture_healthcheck.py (`evaluate_vowen_crash`, `evaluate_mic`, the process/crash-dump
checks, source lines ~40-135). The pipeline no longer imports either of those directly --
it asks a TranscriptProvider for entries and health, and this is the Vowen implementation
of that contract.

Vowen stores its history newest-first, one entry per completed dictation:
    [{"timestamp": "2026-06-01T20:35:00Z", "text": "..."}, ...]
`transcription-history.json` retains a bounded window of recent entries (currently ~100),
so reading the file tail returns the OLDEST retained entry, not the newest -- do not use
tail-reading as a liveness signal.

Two real failure modes this adapter exists to catch (see homebase's
docs/adr and post-mortems for the full incidents this was built from):

  1. Vowen flushes an entry at dictation-END time, which can land a beat AFTER a session's
     stop click. A strict [start, stop] window drops the tail of a long narration, so the
     window here extends `grace_s` past stop by default.
  2. Vowen's process can stay alive while its capture is internally frozen -- a running
     process proves nothing about whether narration is landing. `health()` therefore
     reports the AGE of the newest entry it can see, not just whether Vowen is running.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Callable

from providers.transcript.provider import HealthIssue, ProviderHealth, TranscriptEntry

DEFAULT_HISTORY_PATH = Path(os.environ.get(
    "VOWEN_HISTORY_PATH",
    str(Path.home() / "Library" / "Application Support" / "Vowen" / "transcription-history.json"),
))
DEFAULT_SETTINGS_PATH = Path.home() / "Library" / "Application Support" / "Vowen" / "settings.json"
DEFAULT_CRASH_DIR = Path.home() / "Library" / "Logs" / "DiagnosticReports"
DEFAULT_EXPECTED_MIC = os.environ.get("VOWEN_EXPECTED_MIC", "")

# Small tolerance so an entry whose dictation started a beat before the start click is
# still included in the window.
START_TOLERANCE_S = 5.0
# Vowen stamps an entry at FLUSH time (when dictation ends), which can land a beat after
# the stop click. A strict upper bound of stop_epoch would drop a narration that flushes
# late, so the window extends past stop by this grace.
FLUSH_GRACE_S = 120.0


# ---- window selection (pure; no live system needed) ------------------------------------

def _parse_ts(timestamp: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None


def _read_history(history_path: Path) -> list[dict]:
    try:
        data = json.loads(Path(history_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _select_window(history_path: Path, lo_epoch: float, hi_epoch: float | None) -> list[dict]:
    """Vowen entries with lo_epoch <= timestamp <= hi_epoch (hi None = open), oldest-first.

    Vowen stores entries newest-first. We filter the whole list (not a break-early scan) so
    an out-of-order entry can't truncate the window, then reverse to chronological so a
    multi-entry recording concatenates in the order it was spoken.
    """
    selected: list[dict] = []
    for entry in _read_history(history_path):
        if not isinstance(entry, dict):
            continue
        parsed = _parse_ts(entry.get("timestamp", ""))
        if parsed is None:
            continue
        ts = parsed.timestamp()
        if ts >= lo_epoch and (hi_epoch is None or ts <= hi_epoch):
            selected.append(entry)
    selected.reverse()
    return selected


def _newest_entry_epoch(history_path: Path) -> float | None:
    """Epoch of the freshest entry in the whole history, or None if there are none."""
    epochs = []
    for entry in _read_history(history_path):
        if not isinstance(entry, dict):
            continue
        parsed = _parse_ts(entry.get("timestamp", ""))
        if parsed is not None:
            epochs.append(parsed.timestamp())
    return max(epochs) if epochs else None


# ---- readiness checks (pure; ported 1:1 from capture_healthcheck.py) -------------------

def evaluate_vowen_crash(proc_start: float | None, crash_mtime: float | None) -> HealthIssue:
    """Vowen is suspect if a crash dump is newer than the running process started."""
    if proc_start is None:
        return HealthIssue("vowen_no_recent_crash", False, hard=False,
                            message="could not verify Vowen process start time")
    if crash_mtime is not None and crash_mtime >= proc_start:
        return HealthIssue("vowen_no_recent_crash", False, hard=True,
                            message="Vowen crashed since launch. Restart it: "
                                    "killall Vowen; sleep 2; open /Applications/Vowen.app")
    return HealthIssue("vowen_no_recent_crash", True, hard=True, message="")


def evaluate_mic(settings: object, expected: str) -> HealthIssue:
    """Mic is read from microphoneDeviceName (the real Vowen settings key).

    A blank `expected` means no expectation was configured -- skip the check rather than
    fail every session on an unset env var.
    """
    if not expected:
        return HealthIssue("vowen_mic", True, hard=False, message="no expected mic configured")
    if not isinstance(settings, dict):
        return HealthIssue("vowen_mic", False, hard=False, message="Vowen settings not readable")
    mic = settings.get("microphoneDeviceName") or settings.get("microphoneId") or ""
    if not mic:
        return HealthIssue("vowen_mic", False, hard=False, message="no microphone set in Vowen")
    if mic != expected:
        return HealthIssue("vowen_mic", False, hard=False,
                            message=f"mic is '{mic}', expected '{expected}'")
    return HealthIssue("vowen_mic", True, hard=False, message=f"mic is {mic}")


# ---- live system probes (thin; kept separate so the logic above stays unit-testable) ---

def _pgrep(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                            text=True, timeout=3, check=False)
        return [int(x) for x in r.stdout.split()] if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return []


def _proc_start_epoch(pid: int) -> float | None:
    """Unix start time of a pid via `ps -o lstart=`. None if unavailable."""
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)],
                            capture_output=True, text=True, timeout=3, check=False)
        s = r.stdout.strip()
        if not s:
            return None
        return datetime.datetime.strptime(s, "%a %b %d %H:%M:%S %Y").timestamp()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return None


def _newest_crash_mtime(crash_dir: Path, prefix: str = "Vowen-") -> float | None:
    try:
        dumps = [p for p in crash_dir.glob(f"{prefix}*.ips") if p.is_file()]
    except OSError:
        return None
    return max((p.stat().st_mtime for p in dumps), default=None)


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _to_entry(raw: dict) -> TranscriptEntry:
    ts = raw.get("timestamp", "")
    parsed = _parse_ts(ts)
    epoch = parsed.timestamp() if parsed is not None else 0.0
    return TranscriptEntry(epoch=epoch, ts_iso=ts, text=(raw.get("text") or ""), source="vowen")


class VowenProvider:
    """Reads Vowen's `transcription-history.json`.

    All live-system probes (pgrep, crash-dump mtime, process start time) are injectable so
    tests never need a real Vowen install; see providers/transcript/tests/test_vowen.py.
    """

    name = "vowen"

    def __init__(
        self,
        *,
        history_path: Path | None = None,
        settings_path: Path | None = None,
        crash_dir: Path | None = None,
        expected_mic: str | None = None,
        pgrep: Callable[[str], list[int]] = _pgrep,
        proc_start_epoch: Callable[[int], float | None] = _proc_start_epoch,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self.history_path = history_path or DEFAULT_HISTORY_PATH
        self.settings_path = settings_path or DEFAULT_SETTINGS_PATH
        self.crash_dir = crash_dir or DEFAULT_CRASH_DIR
        self.expected_mic = DEFAULT_EXPECTED_MIC if expected_mic is None else expected_mic
        self._pgrep = pgrep
        self._proc_start_epoch = proc_start_epoch
        self._now = now_fn

    def entries_in_window(
        self,
        start_epoch: float,
        stop_epoch: float | None,
        tolerance_s: float = START_TOLERANCE_S,
        grace_s: float = FLUSH_GRACE_S,
    ) -> list[TranscriptEntry]:
        hi = None if stop_epoch is None else stop_epoch + grace_s
        raw = _select_window(self.history_path, start_epoch - tolerance_s, hi)
        return [_to_entry(e) for e in raw]

    def health(self) -> ProviderHealth:
        pids = self._pgrep("Vowen")
        running = bool(pids)
        issues = [HealthIssue("vowen_running", running, hard=True,
                               message="" if running else "Vowen is not running")]
        if running:
            crash_mtime = _newest_crash_mtime(self.crash_dir)
            issues.append(evaluate_vowen_crash(self._proc_start_epoch(pids[0]), crash_mtime))
        issues.append(evaluate_mic(_read_json(self.settings_path), self.expected_mic))

        newest = _newest_entry_epoch(self.history_path)
        age = (self._now() - newest) if newest is not None else None
        healthy = not any(i.blocking for i in issues)
        message = "" if healthy else next((i.message for i in issues if i.blocking), "")
        return ProviderHealth(name=self.name, healthy=healthy, running=running,
                               last_entry_age_s=age, issues=issues, message=message)
