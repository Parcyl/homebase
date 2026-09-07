#!/usr/bin/env python3
"""Pre-record capture readiness healthcheck.

Runs BEFORE a session starts. Its job is to block the obvious failure modes:
  - the dictation provider is not ready (delegated to provider.health(), see
    providers/transcript/ -- e.g. the vowen adapter checks the process is running and
    hasn't crashed since launch)
  - the screen recorder is not running

HONEST LIMITATION: a pre-record check CANNOT reliably detect a *silent hang* (a dictation
tool running but internally frozen). An idle-but-healthy tool and a frozen one look
identical from the filesystem at rest. The real guard for that case is the during-record
liveness monitor (capture_liveness_monitor.py), which fires if no narration lands within a
grace window. This script is the cheap first gate, not the whole defense.

Exit code 0 = safe to start. Exit code 1 = a hard check failed; do not start.
stdout = JSON for machine parsing. stderr = human-readable status.

NOTE: the "screen recorder running" check below is still hardcoded to Screen Studio.
RecorderAdapter (the recorder-side seam, not yet built) will replace it the same way
providers/transcript/ replaced the dictation checks here -- see notes/bmad/homebase-oss/plan.md S4.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from providers.transcript import HealthIssue, get_provider  # noqa: E402


def _pgrep(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True,
                           text=True, timeout=3, check=False)
        return [int(x) for x in r.stdout.split()] if r.returncode == 0 else []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return []


def run_checks(provider=None) -> list[HealthIssue]:
    """Dictation-provider readiness (via provider.health()) plus the still-hardcoded
    recorder check (see module docstring)."""
    provider = provider or get_provider()
    results = list(provider.health().issues)

    ss_pids = _pgrep("Screen Studio")
    results.append(HealthIssue("screen_studio_running", bool(ss_pids), hard=True,
                               message="" if ss_pids else "Screen Studio is not running"))
    return results


def render_text(results: list[HealthIssue], ok: bool) -> str:
    lines = [f"Capture healthcheck: {'PASS' if ok else 'FAIL'}"]
    for r in results:
        tick = "OK" if r.passed else ("FAIL" if r.blocking else "WARN")
        lines.append(f"  [{tick}] {r.name}: {r.message or 'ok'}")
    if not ok:
        lines.append("")
        lines.append("NOTE: this gate cannot detect a silently-frozen dictation tool. The")
        lines.append("liveness monitor will alert if narration is not landing.")
    return "\n".join(lines)


def main() -> int:
    results = run_checks()
    ok = not any(r.blocking for r in results)
    print(render_text(results, ok), file=sys.stderr)
    print(json.dumps({"passed": ok,
                      "checks": [{"name": r.name, "passed": r.passed, "hard": r.hard,
                                  "message": r.message} for r in results]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
