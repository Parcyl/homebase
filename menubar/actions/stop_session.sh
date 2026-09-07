#!/usr/bin/env bash
# Stop the active recording session. One click.
#
# Stops the configured recorder and (if it has one) the dictation provider's control,
# stops the independent mic backup, then asks record_session.py to capture the dictation
# provider's narration window into transcript.json. Whichever watcher you have running
# (pipeline/pipeline_watcher.py or pipeline/doc_generator.py --watch) picks the session up
# from recordings/<id>/ from here.
#
# GUARD: report whether the dictation provider actually captured anything. Detection is via
# the liveness monitor's .capture-alert sentinel, plus a backstop count of provider entries
# in the session window (through the seam -- see providers/transcript/provider.py -- never
# a specific tool's history file).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"
# Resolved relative to this script's own fixed location on disk, not $HOMEBASE_ROOT -- see
# start_session.sh for why.
RECORD="$HERE/../../pipeline/record_session.py"
AUDIO_BACKUP="$HERE/../../pipeline/capture_audio_backup.py"

# Read the active session id BEFORE stop clears the marker.
SID="$("$PYTHON_BIN" - <<PY
import json, os
p = os.path.join(os.environ.get("HOMEBASE_ROOT", "$HOMEBASE_ROOT"), "agents", ".rec-session.json")
print(json.load(open(p))["session_id"] if os.path.exists(p) else "")
PY
)"

if [[ -z "$SID" ]]; then
    update_state "error" "" '{"error":"stop_session: no active session"}'
    notify "Homebase" "No active session to stop"
    exit 1
fi

SESSION_DIR="$HOMEBASE_ROOT/recordings/$SID"

# Stop the configured recorder and, if present, the dictation provider's control.
recorder_stop "$SESSION_DIR"
dictation_stop

# Stop the liveness monitor (it also self-exits when the marker clears, below).
if [[ -f "$SESSION_DIR/.liveness.pid" ]]; then
    kill "$(cat "$SESSION_DIR/.liveness.pid")" 2>/dev/null || true
    rm -f "$SESSION_DIR/.liveness.pid"
fi

# Cleanly stop the independent mic backup track and learn how much audio it captured.
# BACKUP_DUR is the recorded seconds (0 if none); used below to soften the alarm when the
# dictation provider failed but the backup saved the audio anyway.
BACKUP_LINE="$("$PYTHON_BIN" "$AUDIO_BACKUP" stop --session-dir "$SESSION_DIR" 2>/dev/null || echo "none")"
BACKUP_DUR="$(echo "$BACKUP_LINE" | awk '{print ($1=="ok") ? $2 : 0}')"
BACKUP_OK="$("$PYTHON_BIN" -c "import sys; print(1 if float(sys.argv[1])>0 else 0)" "$BACKUP_DUR" 2>/dev/null || echo 0)"

# Did the dictation provider actually capture narration? Sentinel from the liveness
# monitor is authoritative; a zero entry count in the window is the backstop. Counted
# through the TranscriptProvider seam, not a specific tool's history file.
PROVIDER_COUNT="$("$PYTHON_BIN" - <<PY
import json, sys
sys.path.insert(0, "${_REPO_ROOT_DEFAULT}")
from pathlib import Path
from providers.transcript import get_provider

session_dir = Path("${SESSION_DIR}")
try:
    meta = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
    start_epoch = float(meta["start_epoch"])
except Exception:
    print(-1)
else:
    provider = get_provider(session_dir=session_dir)
    print(len(provider.entries_in_window(start_epoch, None)))
PY
)"

if [[ -f "$SESSION_DIR/.capture-alert" || "$PROVIDER_COUNT" == "0" ]]; then
    if [[ "$BACKUP_OK" == "1" ]]; then
        # The dictation provider failed, but the independent backup saved the audio.
        notify "Homebase" "Dictation provider empty, but backup audio (${BACKUP_DUR}s) saved. Narration recovers from backup."
        echo "Dictation provider captured nothing (count=$PROVIDER_COUNT) -- but backup-audio.wav = ${BACKUP_DUR}s."
        echo "  The pipeline will transcribe the backup; narration is NOT lost. Export your MP4 here:"
        echo "   $SESSION_DIR"
    else
        notify "Homebase" "CAPTURE PROBLEM: dictation provider AND backup both empty. Check your dictation tool before re-recording."
        echo "Dictation provider captured no narration (count=$PROVIDER_COUNT) AND backup audio is empty. Session preserved at:"
        echo "   $SESSION_DIR"
    fi
else
    notify "Homebase" "Captured: $SID ($PROVIDER_COUNT entries, +${BACKUP_DUR}s backup)."
    echo "Stopped session $SID -- provider entries: $PROVIDER_COUNT, backup audio: ${BACKUP_DUR}s"
fi

# Capture the narration window (best-effort; often deferred to the watcher -- see
# record_session.py's stop_session docstring) and clear the marker.
"$PYTHON_BIN" "$RECORD" stop || true

update_state "ready" "$SID" '{"message":"awaiting pipeline"}'

if [[ "$DRY_RUN" != "1" ]]; then
    open "$SESSION_DIR" 2>/dev/null || true
fi

echo "Export your recording to: $SESSION_DIR/raw.mp4 (skip this if your recorder adapter already delivers it there)"
