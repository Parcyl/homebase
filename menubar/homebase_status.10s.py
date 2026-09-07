#!/usr/bin/env python3
# <bitbar.title>Homebase</bitbar.title>
# <bitbar.version>v0.1.0</bitbar.version>
# <bitbar.desc>Live status and front-door actions for the homebase pipeline.</bitbar.desc>
# <bitbar.dependencies>python3</bitbar.dependencies>
# <swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
"""SwiftBar plugin for homebase.

Renders the menu bar title (color reflects health) and a dropdown that surfaces
current pipeline state, an optional activity feed, and one-click actions.

Refresh cadence is fixed by the filename suffix (.10s.). Pure stdlib so each
refresh costs near nothing.

Set HOMEBASE_ROOT in SwiftBar's plugin environment (or ~/.zshrc) if this repo isn't
checked out where lib/state.py's default resolution expects it.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly or via SwiftBar without PYTHONPATH gymnastics
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from lib.state import (  # noqa: E402
    StateView,
    capture_alert,
    health_ok,
    homebase_root,
    latest_handoff_path,
    latest_prd_path,
    read_state,
    recent_log_lines,
)

GREEN = "#1DAF29"
YELLOW = "#E8B900"
RED = "#D33333"
DIM = "#888888"

STAGE_LABELS = {
    "idle": "Idle",
    "recording": "Recording",
    "ready": "Recording stopped (awaiting pipeline)",
    "transcribing": "Transcribing",
    "classifying": "Classifying",
    "extracting": "Extracting",
    "grounding": "Grounding",
    "comparing": "Comparing patterns",
    "generating": "Generating PRD",
    "filing": "Filing outputs",
    "complete": "Complete",
    "error": "Error",
    "unknown": "Unknown",
}


def _color_for(state: StateView, healthy: bool) -> str:
    if not healthy or state.is_error:
        return RED
    if state.is_processing:
        return YELLOW
    return GREEN


def _title_line(state: StateView, healthy: bool) -> str:
    color = _color_for(state, healthy)
    if capture_alert():
        color = RED
    # SwiftBar SF Symbol; falls back to dot in narrow contexts
    return f"● Homebase | color={color} sfsymbol=circle.fill"


def _scripts_dir() -> Path:
    """Folder where the action shell scripts live.

    Action scripts are kept in an `actions/` subfolder so the plugin folder
    itself stays minimal. Resolves the symlink so the path is correct whether
    the plugin is invoked through ~/SwiftBar/ symlink or directly.
    """
    return Path(__file__).resolve().parent / "actions"


def render(state: StateView, healthy: bool, log_lines: list[str]) -> str:
    lines: list[str] = []
    lines.append(_title_line(state, healthy))
    lines.append("---")

    # Status block
    label = STAGE_LABELS.get(state.stage, state.stage)
    lines.append(f"Stage: {label} | color={_color_for(state, healthy)}")
    if state.session_id:
        lines.append(f"Session: {state.session_id} | color={DIM}")
    if state.updated_at:
        lines.append(f"Updated: {state.updated_at} | color={DIM}")
    if state.error:
        lines.append(f"Error: {state.error} | color={RED}")
    if not state.readable:
        lines.append("State file unreadable. Try Restart Services. | color=" + RED)
    lines.append(
        "Intelligence: " + ("up" if healthy else "down") + f" | color={GREEN if healthy else RED}"
    )

    _alert = capture_alert()
    if _alert:
        lines.append(f"CAPTURE FAILED: {_alert} | color={RED}")

    # Recent activity (optional -- see recent_log_lines in lib/state.py)
    lines.append("---")
    lines.append("Recent activity")
    if log_lines:
        for ln in log_lines:
            # SwiftBar uses pipes as separators; sanitize
            safe = ln.replace("|", "/")
            lines.append(f"-- {safe} | length=120 size=11 color={DIM}")
    else:
        lines.append(f"-- (no log entries yet) | color={DIM}")

    # Actions
    lines.append("---")
    lines.append("Actions")
    scripts = _scripts_dir()

    def action(label: str, script: str, *, refresh: bool = True, terminal: bool = False) -> str:
        path = scripts / script
        return (
            f"{label} | shell={path} terminal={'true' if terminal else 'false'} "
            f"refresh={'true' if refresh else 'false'}"
        )

    if state.stage == "recording":
        lines.append(action("◼ Stop Session", "stop_session.sh"))
    else:
        lines.append(action("● Start Session", "start_session.sh"))

    handoff = latest_handoff_path()
    prd = latest_prd_path()
    has_handoff = handoff is not None
    has_prd = prd is not None

    handoff_label = "📋 Copy Handoff Prompt" + ("" if has_handoff else " (none yet)")
    lines.append(
        action(handoff_label, "copy_handoff.sh")
        + ("" if has_handoff else f" color={DIM}")
    )

    prd_label = "📄 Open Last PRD" + ("" if has_prd else " (none yet)")
    lines.append(
        action(prd_label, "open_last_prd.sh")
        + ("" if has_prd else f" color={DIM}")
    )

    lines.append(action("📑 Open Last Digest", "open_last_digest.sh"))
    lines.append(action("📥 Open Inbox", "open_inbox.sh"))
    lines.append(action("🛠 Tail Logs", "tail_logs.sh", terminal=True))
    lines.append(action("🔁 Restart Services", "restart_services.sh"))

    lines.append("---")
    lines.append(f"HOMEBASE_ROOT: {homebase_root()} | color={DIM} size=10")
    return "\n".join(lines) + "\n"


def main() -> int:
    state = read_state()
    healthy = health_ok()
    log_lines = recent_log_lines()
    sys.stdout.write(render(state, healthy, log_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
