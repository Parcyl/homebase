"""Tests for the capture guard pipeline scripts (healthcheck aggregation + the liveness
monitor's pure alert decision).

The dictation-provider-specific readiness checks and window selection now live in, and are
tested by, providers/transcript/tests/ -- these tests exercise what's left in pipeline/:
capture_healthcheck.py's aggregation and capture_liveness_monitor.py's assess().
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


# ---------- capture_healthcheck.run_checks: provider issues + the (still-hardcoded)
# ---------- Screen Studio check are aggregated together ----------

def test_run_checks_surfaces_provider_issues():
    issue = HealthIssue("provider_running", False, hard=True, message="provider is not running")
    provider = _StubProvider(ProviderHealth(name="stub", healthy=False, issues=[issue]))
    results = hc.run_checks(provider)
    assert issue in results


def test_run_checks_always_appends_screen_studio_check():
    provider = _StubProvider(ProviderHealth(name="file", healthy=True, issues=[]))
    results = hc.run_checks(provider)
    names = [r.name for r in results]
    assert "screen_studio_running" in names


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
