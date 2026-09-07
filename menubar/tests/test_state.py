"""Tests for menu_bar.lib.state."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from lib.state import (
    capture_alert,
    health_ok,
    latest_digest_path,
    latest_handoff_path,
    latest_prd_path,
    read_state,
    recent_log_lines,
)


def _write_state(homebase: Path, payload: dict) -> None:
    p = homebase / "agents" / "pipeline-state.json"
    p.write_text(json.dumps(payload), encoding="utf-8")


def test_read_state_returns_unknown_when_missing(fake_homebase: Path):
    s = read_state(fake_homebase)
    assert s.stage == "unknown"
    assert s.readable is False


def test_read_state_parses_full_payload(fake_homebase: Path):
    _write_state(
        fake_homebase,
        {
            "stage": "classifying",
            "session_id": "2026-05-25T10-00-00-test",
            "updated_at": "2026-05-25T10:00:05Z",
            "last_prd": None,
            "last_handoff": None,
        },
    )
    s = read_state(fake_homebase)
    assert s.stage == "classifying"
    assert s.session_id == "2026-05-25T10-00-00-test"
    assert s.is_processing is True
    assert s.is_idle_or_done is False
    assert s.readable is True


def test_read_state_tolerates_garbage(fake_homebase: Path):
    (fake_homebase / "agents" / "pipeline-state.json").write_text("not json")
    s = read_state(fake_homebase)
    assert s.stage == "unknown"
    assert s.readable is False


def test_recent_log_lines_returns_last_n_reversed(fake_homebase: Path):
    log = fake_homebase / "agents" / "activity-log.md"
    log.write_text(
        "# Activity\n\n"
        "- [2026-05-25T10:00:00Z] [T01] [file] [s1] [ok] one\n"
        "- [2026-05-25T10:01:00Z] [T01] [file] [s2] [ok] two\n"
        "- [2026-05-25T10:02:00Z] [T01] [file] [s3] [ok] three\n",
    )
    lines = recent_log_lines(fake_homebase, n=2)
    assert len(lines) == 2
    assert "three" in lines[0]
    assert "two" in lines[1]


def test_recent_log_lines_empty_when_no_file(fake_homebase: Path):
    # Nothing writes agents/activity-log.md by default -- bring your own.
    assert recent_log_lines(fake_homebase) == []


def test_health_ok_true_on_200(fake_homebase: Path):
    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    with patch("lib.state.urlopen", return_value=Resp()):
        assert health_ok("http://x", timeout=0.1) is True


def test_health_ok_false_on_error(fake_homebase: Path):
    with patch("lib.state.urlopen", side_effect=OSError("boom")):
        assert health_ok("http://x", timeout=0.1) is False


def test_latest_prd_and_handoff(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-t"
    (fake_homebase / "prds" / sid).mkdir()
    prd = fake_homebase / "prds" / sid / "PRD.md"
    handoff = fake_homebase / "prds" / sid / "handoff-prompt.md"
    prd.write_text("# PRD")
    handoff.write_text("# Handoff")
    assert latest_prd_path(fake_homebase) == prd
    assert latest_handoff_path(fake_homebase) == handoff


def test_latest_digest(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-t"
    (fake_homebase / "recordings" / sid).mkdir()
    digest = fake_homebase / "recordings" / sid / "DIGEST.md"
    digest.write_text("# Digest")
    assert latest_digest_path(fake_homebase) == digest


def test_latest_digest_none_when_absent(fake_homebase: Path):
    assert latest_digest_path(fake_homebase) is None


def test_capture_alert_none_when_no_sessions(fake_homebase: Path):
    assert capture_alert(fake_homebase) is None


def test_capture_alert_reads_newest_session(fake_homebase: Path):
    old = fake_homebase / "recordings" / "2026-01-01T00-00-00-a"
    new = fake_homebase / "recordings" / "2026-02-01T00-00-00-b"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (new / ".capture-alert").write_text("provider frozen\nsecond line\n", encoding="utf-8")
    assert capture_alert(fake_homebase) == "provider frozen"
