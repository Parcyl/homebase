"""Smoke tests for the action shell scripts. Run each with HOMEBASE_DRY_RUN=1.

These tests do not launch a real screen recorder or dictation tool -- with RECORDER and
DICTATION_PROVIDER unset, the seams default to FileRecorder/FileProvider (see
providers/recorder/__init__.py, providers/transcript/__init__.py), which are no-op/read-only
and touch nothing outside the fake HOMEBASE_ROOT. They verify the scripts parse correctly,
write to pipeline-state.json, and exit cleanly under dry-run mode.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "actions"


def _run(script: str, homebase: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(
        {
            "HOMEBASE_ROOT": str(homebase),
            "HOMEBASE_DRY_RUN": "1",
            "PYTHON_BIN": shutil.which("python3.12") or shutil.which("python3") or "python3",
        }
    )
    # HOMEBASE_ROOT here is a fake, data-only directory (see fake_homebase in conftest.py).
    # The scripts resolve pipeline/*.py relative to their own location on disk (see
    # start_session.sh's HERE-relative comment), so this never needs to contain code.
    # RECORDER/DICTATION_PROVIDER are stripped so a developer's real shell config never
    # makes these tests try to drive an actual screen recorder or dictation tool.
    env.pop("RECORDER", None)
    env.pop("DICTATION_PROVIDER", None)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["/bin/bash", str(SCRIPTS_DIR / script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_start_session_writes_state_and_marker(fake_homebase: Path):
    r = _run("start_session.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "recording"
    assert state["session_id"]
    marker = json.loads((fake_homebase / "agents" / ".rec-session.json").read_text())
    assert marker["session_id"] == state["session_id"]
    session_dir = fake_homebase / "recordings" / state["session_id"]
    assert session_dir.is_dir()
    assert (session_dir / "session.json").exists()


def test_stop_session_errors_without_session(fake_homebase: Path):
    r = _run("stop_session.sh", fake_homebase)
    assert r.returncode == 1
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "error"


def test_stop_session_after_start(fake_homebase: Path):
    _run("start_session.sh", fake_homebase)
    r = _run("stop_session.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "ready"
    # marker cleared so a second stop is a no-op error
    assert not (fake_homebase / "agents" / ".rec-session.json").exists()


def test_stop_session_after_start_clears_liveness_pid(fake_homebase: Path):
    """The liveness monitor is never spawned under DRY_RUN, so there is no .liveness.pid to
    clean up -- stop must not fail when it's absent."""
    _run("start_session.sh", fake_homebase)
    r = _run("stop_session.sh", fake_homebase)
    assert r.returncode == 0, r.stderr


def test_open_inbox_dry(fake_homebase: Path):
    r = _run("open_inbox.sh", fake_homebase)
    assert r.returncode == 0
    assert (fake_homebase / "inbox").exists()


def test_copy_handoff_no_handoff(fake_homebase: Path):
    r = _run("copy_handoff.sh", fake_homebase)
    assert r.returncode == 1
    assert "no handoff found" in r.stdout


def test_copy_handoff_finds_latest(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-x"
    (fake_homebase / "prds" / sid).mkdir()
    (fake_homebase / "prds" / sid / "handoff-prompt.md").write_text("ok")
    r = _run("copy_handoff.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    assert "would copy" in r.stdout
    assert sid in r.stdout


def test_open_last_prd_no_prd(fake_homebase: Path):
    r = _run("open_last_prd.sh", fake_homebase)
    assert r.returncode == 1


def test_open_last_prd_finds_latest(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-y"
    (fake_homebase / "prds" / sid).mkdir()
    (fake_homebase / "prds" / sid / "PRD.md").write_text("ok")
    r = _run("open_last_prd.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    assert "would open" in r.stdout
    # Opens in VS Code explicitly (default), not the system .md default
    assert "Visual Studio Code" in r.stdout


def test_open_last_prd_editor_is_configurable(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-z"
    (fake_homebase / "prds" / sid).mkdir()
    (fake_homebase / "prds" / sid / "PRD.md").write_text("ok")
    r = _run("open_last_prd.sh", fake_homebase, extra_env={"HOMEBASE_EDITOR_APP": "Zed"})
    assert r.returncode == 0, r.stderr
    assert "Zed" in r.stdout


def test_open_last_digest_no_digest_is_clean(fake_homebase: Path):
    r = _run("open_last_digest.sh", fake_homebase)
    assert r.returncode == 0, r.stderr


def test_open_last_digest_finds_latest(fake_homebase: Path):
    sid = "2026-05-25T11-00-00-w"
    (fake_homebase / "recordings" / sid).mkdir()
    (fake_homebase / "recordings" / sid / "DIGEST.md").write_text("ok")
    r = _run("open_last_digest.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    assert "would open" in r.stdout
    assert sid in r.stdout


def test_restart_services_dry(fake_homebase: Path):
    r = _run("restart_services.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    state = json.loads((fake_homebase / "agents" / "pipeline-state.json").read_text())
    assert state["stage"] == "idle"


def test_tail_logs_dry(fake_homebase: Path):
    r = _run("tail_logs.sh", fake_homebase)
    assert r.returncode == 0, r.stderr
    assert "would tail" in r.stdout


@pytest.mark.parametrize(
    "script",
    [
        "start_session.sh",
        "stop_session.sh",
        "copy_handoff.sh",
        "open_last_prd.sh",
        "open_last_digest.sh",
        "open_inbox.sh",
        "tail_logs.sh",
        "restart_services.sh",
    ],
)
def test_every_action_script_is_valid_bash(script: str):
    r = subprocess.run(["/bin/bash", "-n", str(SCRIPTS_DIR / script)],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0, r.stderr
