"""TranscriptProvider: the pipeline never talks to a dictation tool directly.

The recording flow narrates in whatever tool the operator has running, or nothing at all --
just a file dropped by hand. The pipeline only ever asks a provider "what did the operator
say in this time window" and, separately, "are you healthy". A new dictation tool is a new
adapter module in providers/transcript/, never a change to pipeline/record_session.py or
the capture guards.

Adapters shipped: one per supported dictation tool (see providers/transcript/*.py), plus
FileProvider (the default -- bring your own transcript.json, zero tool assumptions).
Selected via providers.transcript.get_provider(), driven by the DICTATION_PROVIDER env var.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TranscriptEntry:
    """One narration entry, normalized across providers."""

    epoch: float  # unix seconds
    ts_iso: str
    text: str
    source: str  # provider name, for provenance


@dataclass(frozen=True)
class HealthIssue:
    """One named readiness/liveness check a provider (or the pipeline, for a non-provider
    concern like the recorder) can report.

    Mirrors the hard/soft distinction the original capture_healthcheck.py used: a hard
    failure should block starting a session, a soft one is advisory only.
    """

    name: str
    passed: bool
    hard: bool
    message: str = ""

    @property
    def blocking(self) -> bool:
        return self.hard and not self.passed


@dataclass(frozen=True)
class ProviderHealth:
    """A provider's readiness/liveness snapshot, independent of any one session's window.

    `running` is best-effort and may be None for providers with no process to check at all
    (FileProvider -- there is nothing to poll, the operator just drops a file per session).

    `last_entry_age_s` is the age, in seconds as of this call, of the newest entry the
    provider can currently see across its whole history -- None if it has no entries yet or
    cannot determine one. This is deliberately an ARTIFACT check, not a process check: a
    dictation tool can stay running while its capture is dead (see providers/transcript/vowen.py
    for the incident this guards against), so "is the tool alive" proves nothing on its own.
    The liveness monitor watches this value drop and grow, not `running`.

    `healthy` is the overall verdict: no hard-blocking issue in `issues` is failing.
    """

    name: str
    healthy: bool
    running: bool | None = None
    last_entry_age_s: float | None = None
    issues: list[HealthIssue] = field(default_factory=list)
    message: str = ""


@runtime_checkable
class TranscriptProvider(Protocol):
    """A source of spoken narration, windowed to a recording session."""

    name: str

    def entries_in_window(
        self,
        start_epoch: float,
        stop_epoch: float | None,
        tolerance_s: float = 60,
        grace_s: float = 90,
    ) -> list[TranscriptEntry]:
        """Entries in [start_epoch - tolerance_s, stop_epoch + grace_s], oldest-first.

        stop_epoch=None means an open upper bound (grace_s is then unused). The tolerance
        catches an entry that started a beat before the start click; the grace catches a
        tool that flushes its final entry a beat after the stop click (see vowen.py for why
        this matters -- it is not a hypothetical).
        """
        ...

    def health(self) -> ProviderHealth:
        """Best-effort readiness/liveness snapshot, independent of any one session."""
        ...
