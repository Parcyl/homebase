"""Tests for the capture guard pipeline scripts (healthcheck aggregation + the liveness
monitor's pure alert decision).

The dictation-provider-specific readiness checks and window selection now live in, and are
tested by, providers/transcript/tests/; the recorder-specific liveness check (e.g. Screen
Studio's pgrep) lives in, and is tested by, providers/recorder/tests/ -- these tests exercise
what's left in pipeline/: capture_healthcheck.py's aggregation of both seams and
capture_liveness_monitor.py's assess().
"""
from __future__ import annotations

import capture_healthcheck as hc
import capture_liveness_monitor as lm
from providers.transcript.provider import HealthIssue, ProviderHealth


class _StubProvider:
    """A TranscriptProvider stand-in with a canned health() result, for testing the
    pipeline scripts without a real dictation-provider adapter."""

    name = "stub"

    def __init__(self, health: ProviderHealth):
        self._health = health

    def entries_in_window(self, *a, **k):
        return []

    def health(self) -> ProviderHealth:
        return self._health


class _StubRecorder:
    """A RecorderAdapter stand-in with a canned is_running() result, for testing the
    healthcheck's aggregation without a real recorder adapter."""

    def __init__(self, name: str, running: bool | None = None):
        self.name = name
        self._running = running

    def start(self, session_dir):
        pass

    def stop(self, session_dir):
        pass

    def resolve_master(self, session_start_epoch, session_dir):
        return None

    def is_running(self) -> bool | None:
        return self._running


class _BareStubRecorder:
    """A RecorderAdapter stand-in with NO is_running() at all -- a third-party recorder
    that never opted into the liveness seam. run_checks must skip it, not crash."""

    def __init__(self, name: str):
        self.name = name

    def start(self, session_dir):
        pass

    def stop(self, session_dir):
        pass

    def resolve_master(self, session_start_epoch, session_dir):
        return None


# ---------- capture_healthcheck.run_checks: provider issues + the recorder's own liveness
# ---------- check (if it has one) are aggregated together ----------

def test_run_checks_surfaces_provider_issues():
    issue = HealthIssue("provider_running", False, hard=True, message="provider is not running")
    provider = _StubProvider(ProviderHealth(name="stub", healthy=False, issues=[issue]))
    recorder = _StubRecorder("stub-recorder", running=True)
    results = hc.run_checks(provider, recorder)
    assert issue in results


def test_run_checks_appends_recorder_liveness_when_supported():
    provider = _StubProvider(ProviderHealth(name="file", healthy=True, issues=[]))
    recorder = _StubRecorder("stub-recorder", running=False)
    results = hc.run_checks(provider, recorder)
    names = [r.name for r in results]
    assert "stub-recorder_running" in names
    issue = next(r for r in results if r.name == "stub-recorder_running")
    assert not issue.passed and issue.blocking


def test_run_checks_skips_recorder_check_when_not_applicable():
    """A recorder with nothing to poll (e.g. FileRecorder) returns None from is_running(),
    which means 'not applicable', not 'not running' -- the check must be skipped, not
    treated as a failure."""
    provider = _StubProvider(ProviderHealth(name="file", healthy=True, issues=[]))
    recorder = _StubRecorder("file", running=None)
    results = hc.run_checks(provider, recorder)
    names = [r.name for r in results]
    assert "file_running" not in names


def test_run_checks_skips_recorder_with_no_liveness_concept():
    """A recorder that doesn't implement is_running() at all is skipped, not crashed on."""
    provider = _StubProvider(ProviderHealth(name="file", healthy=True, issues=[]))
    recorder = _BareStubRecorder("bare-recorder")
    results = hc.run_checks(provider, recorder)
    names = [r.name for r in results]
    assert "bare-recorder_running" not in names


def test_render_text_marks_pass_or_fail():
    ok_text = hc.render_text([], True)
    fail_text = hc.render_text([], False)
    assert "PASS" in ok_text
    assert "FAIL" in fail_text


# ---------- capture_liveness_monitor.assess(): the artifact-freshness alert decision ----------

def test_frozen_provider_past_grace_alerts():
    # No entry has ever landed (last_entry_age_s=None) and we're well past the grace.
    alert, msg = lm.assess(seconds_since_start=lm.FIRST_ENTRY_GRACE_S + 1, last_entry_age_s=None)
    assert alert and "frozen" in msg.lower()


def test_no_entries_within_grace_is_quiet():
    alert, _ = lm.assess(seconds_since_start=10, last_entry_age_s=None)
    assert not alert


def test_entry_predating_session_start_counts_as_nothing_new():
    # last_entry_age_s > seconds_since_start means the newest entry the provider can see is
    # OLDER than the session -- e.g. leftover history from before this session began.
    alert, _ = lm.assess(seconds_since_start=10, last_entry_age_s=500)
    assert not alert  # still within grace


def test_entry_predating_session_start_alerts_past_grace():
    alert, msg = lm.assess(seconds_since_start=lm.FIRST_ENTRY_GRACE_S + 1, last_entry_age_s=99999)
    assert alert and "frozen" in msg.lower()


def test_stall_after_entries_alerts():
    # An entry landed 40 min into a 40-min-plus session, but it's now stale by > STALL_S.
    alert, msg = lm.assess(seconds_since_start=4000, last_entry_age_s=lm.STALL_S + 1)
    assert alert and "mid-session" in msg.lower()


def test_healthy_flow_is_quiet():
    alert, _ = lm.assess(seconds_since_start=4000, last_entry_age_s=10)
    assert not alert


def test_boundary_entry_exactly_at_start_counts_as_landed():
    # last_entry_age_s == seconds_since_start means the entry landed exactly at session
    # start -- treated as landed (not "nothing new"), so only the stall threshold applies,
    # and it's still fresh here (well under STALL_S) so this stays quiet.
    alert, _ = lm.assess(seconds_since_start=10, last_entry_age_s=10)
    assert not alert


def test_boundary_stall_threshold_is_inclusive():
    alert, msg = lm.assess(seconds_since_start=4000, last_entry_age_s=lm.STALL_S)
    assert alert and "mid-session" in msg.lower()
