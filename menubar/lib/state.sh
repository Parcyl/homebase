#!/usr/bin/env bash
# Shared helpers for menu bar action scripts.
# Source via:  source "$(dirname "$0")/lib/state.sh"

set -euo pipefail

# menubar/lib/state.sh -> menubar/lib -> menubar -> repo root. No hardcoded path: this
# resolves relative to the file itself, so it works wherever the repo is checked out.
_STATE_SH_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_REPO_ROOT_DEFAULT="$(cd "$_STATE_SH_DIR/../.." && pwd)"

HOMEBASE_ROOT="${HOMEBASE_ROOT:-$_REPO_ROOT_DEFAULT}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
LANGGRAPH_URL="${LANGGRAPH_URL:-http://127.0.0.1:8080}"
LANGGRAPH_PORT="${LANGGRAPH_PORT:-8080}"
# Exported (not just set) so every pipeline/*.py child process this script shells out to
# sees the same HOMEBASE_ROOT, including when an operator points it somewhere other than
# this checkout for session data.
export HOMEBASE_ROOT PYTHON_BIN LANGGRAPH_URL LANGGRAPH_PORT

# Editor for opening files (PRDs, etc.). We open files in a NAMED app rather than the
# system default, because the default handler for .md may be something else entirely.
# Override with HOMEBASE_EDITOR_APP. Must be an app name `open -a` understands.
HOMEBASE_EDITOR_APP="${HOMEBASE_EDITOR_APP:-Visual Studio Code}"

# Dry-run mode disables app launches and side effects beyond state writes
DRY_RUN="${HOMEBASE_DRY_RUN:-0}"

# update_state STAGE [SESSION_ID] [EXTRA_JSON_FIELDS]
# Atomically writes pipeline-state.json -- the same contract intelligence/app/pipeline_state.py
# and pipeline/doc_generator.py write through (see notes/bmad/homebase-oss/design.md).
update_state() {
    local stage="$1"
    local session_id="${2:-}"
    local extra="${3-}"
    if [[ -z "$extra" ]]; then
        extra='{}'
    fi

    "$PYTHON_BIN" - <<PY
import json, os, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

stage = "${stage}"
session_id = "${session_id}" or None
extra = json.loads('''${extra}''')

root = Path(os.environ.get("HOMEBASE_ROOT", "${HOMEBASE_ROOT}"))
path = root / "agents" / "pipeline-state.json"
path.parent.mkdir(parents=True, exist_ok=True)

current = {}
if path.exists():
    try:
        current = json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        current = {}

now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
if stage == "recording" and current.get("stage") != "recording":
    current["started_at"] = now
if stage == "idle":
    current["started_at"] = None
    current["error"] = None

current["stage"] = stage
if session_id:
    current["session_id"] = session_id
current["updated_at"] = now
if stage != "error":
    current["error"] = None if stage not in {"recording", "ready"} else current.get("error")
current.update(extra)

fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(json.dumps(current, indent=2) + "\n")
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp, path)
PY
}

# recorder_start SESSION_DIR
# Drives the configured RecorderAdapter's start() (see providers/recorder/). The menu bar
# never assumes which recorder is configured -- RECORDER selects it (screen-studio | file).
recorder_start() {
    local session_dir="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] would call recorder.start($session_dir)"
        return 0
    fi
    "$PYTHON_BIN" - <<PY
import sys
sys.path.insert(0, "${_REPO_ROOT_DEFAULT}")
from pathlib import Path
from providers.recorder import get_recorder
get_recorder().start(Path("${session_dir}"))
PY
}

# recorder_stop SESSION_DIR
recorder_stop() {
    local session_dir="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] would call recorder.stop($session_dir)"
        return 0
    fi
    "$PYTHON_BIN" - <<PY
import sys
sys.path.insert(0, "${_REPO_ROOT_DEFAULT}")
from pathlib import Path
from providers.recorder import get_recorder
get_recorder().stop(Path("${session_dir}"))
PY
}

# dictation_start / dictation_stop
# Calls the configured TranscriptProvider's start()/stop() control ONLY IF it has one.
# start()/stop() are NOT part of the TranscriptProvider protocol (see
# providers/transcript/provider.py) -- most providers are read-only (FileProvider,
# WisprFlowProvider), so this is a best-effort, duck-typed no-op for them. Today only
# VowenProvider implements it (providers/transcript/vowen.py), driving Vowen's Hands-Free
# Mode shortcut via AppleScript, same mechanism as the recorder control above.
dictation_start() {
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] would call dictation provider start(), if it has one"
        return 0
    fi
    "$PYTHON_BIN" - <<PY
import sys
sys.path.insert(0, "${_REPO_ROOT_DEFAULT}")
from providers.transcript import get_provider
provider = get_provider()
start = getattr(provider, "start", None)
if callable(start):
    start()
PY
}

dictation_stop() {
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] would call dictation provider stop(), if it has one"
        return 0
    fi
    "$PYTHON_BIN" - <<PY
import sys
sys.path.insert(0, "${_REPO_ROOT_DEFAULT}")
from providers.transcript import get_provider
provider = get_provider()
stop = getattr(provider, "stop", None)
if callable(stop):
    stop()
PY
}

# Newest file named "$2" anywhere under directory "$1", or empty string.
# Portable across BSD stat (macOS: -f "%m") and GNU stat (Linux: -c "%Y").
_latest_by_mtime() {
    local root="$1" name="$2" best_t=-1 best_p="" t p gnu=0
    # GNU stat (Linux) supports --version and formats with -c "%Y"; BSD stat (macOS)
    # rejects --version and formats with -f "%m". Detect once; do NOT rely on -f failing
    # on GNU, because GNU treats -f as filesystem mode and exits 0 with the wrong output.
    stat --version >/dev/null 2>&1 && gnu=1
    while IFS= read -r p; do
        if [ "$gnu" = 1 ]; then t=$(stat -c "%Y" "$p" 2>/dev/null); else t=$(stat -f "%m" "$p" 2>/dev/null); fi
        case "$t" in ''|*[!0-9]*) continue ;; esac   # only accept an integer epoch mtime
        if [ "$t" -gt "$best_t" ]; then best_t="$t"; best_p="$p"; fi
    done < <(find "$root" -name "$name" -type f 2>/dev/null)
    [ -n "$best_p" ] && printf '%s\n' "$best_p"
}

# Returns latest PRD.md path under prds/, or empty string
latest_prd() {
    _latest_by_mtime "$HOMEBASE_ROOT/prds" PRD.md
}

latest_handoff() {
    _latest_by_mtime "$HOMEBASE_ROOT/prds" handoff-prompt.md
}

latest_digest() {
    _latest_by_mtime "$HOMEBASE_ROOT/recordings" DIGEST.md
}

run_osascript() {
    local script_path="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] osascript $script_path"
        return 0
    fi
    if [[ -f "$script_path" ]]; then
        osascript "$script_path" || echo "[warn] osascript $script_path returned $?"
    else
        echo "[warn] AppleScript missing: $script_path"
    fi
}

notify() {
    local title="$1"; local message="$2"
    if [[ "$DRY_RUN" == "1" ]]; then return 0; fi
    osascript -e "display notification \"$message\" with title \"$title\"" 2>/dev/null || true
}

# open_in_editor FILE
# Open FILE in HOMEBASE_EDITOR_APP (default Visual Studio Code), not the system .md
# default. Falls back to bare `open` if the named editor is unavailable.
open_in_editor() {
    local file="$1"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "[dry-run] would open $file in $HOMEBASE_EDITOR_APP"
        return 0
    fi
    open -a "$HOMEBASE_EDITOR_APP" "$file" 2>/dev/null || open "$file"
}
