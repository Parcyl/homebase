#!/usr/bin/env bash
# Start a recording session. One click.
#
# GUARDS (ported from the source project's most battle-tested capture flow, after a
# capture was silently lost mid-narration):
#  1. Pre-record healthcheck blocks the start if the configured dictation provider or
#     recorder are obviously not ready (pipeline/capture_healthcheck.py).
#  2. A background liveness monitor is spawned that alerts within ~90s if narration is not
#     landing -- the real catch for a dictation tool that silently freezes. See
#     pipeline/capture_liveness_monitor.py.
#  3. An independent ffmpeg mic backup track is recorded alongside the dictation provider
#     via the com.homebase.audiobackup launchd agent. If the provider captures nothing, the
#     pipeline can transcribe this backup so the narration is not lost. See
#     pipeline/capture_audio_backup.py.
#
# Recording control is delegated to the configured RecorderAdapter (recorder_start, in
# lib/state.sh) and, if the configured dictation provider exposes one, its optional
# start() control (dictation_start) -- see providers/recorder/adapter.py and
# providers/transcript/provider.py. This script never assumes which tool is configured.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"
# Resolved relative to this script's own fixed location on disk (menubar/actions ->
# repo root), NOT $HOMEBASE_ROOT -- HOMEBASE_ROOT names where session DATA lives and can be
# pointed elsewhere (see lib/state.sh), but the pipeline/ code always lives with this repo.
RECORD="$HERE/../../pipeline/record_session.py"
HEALTHCHECK="$HERE/../../pipeline/capture_healthcheck.py"
LIVENESS="$HERE/../../pipeline/capture_liveness_monitor.py"

# Pre-record healthcheck. Blocks if the dictation provider or recorder are not ready.
# Skipped under DRY_RUN (tests/CI): the healthcheck probes live processes, which are not
# present in a test environment. Production never sets DRY_RUN, so a real start always
# runs the full healthcheck.
if [[ "$DRY_RUN" != "1" ]]; then
    HC_OUT="$(mktemp -t homebase-hc)"
    if ! "$PYTHON_BIN" "$HEALTHCHECK" >/dev/null 2>"$HC_OUT"; then
        REASON="$(grep '\[FAIL\]' "$HC_OUT" | head -1 | sed 's/^ *//')"
        notify "Homebase" "Cannot start: ${REASON:-capture not ready}"
        echo "Healthcheck FAILED. Session NOT started:"
        cat "$HC_OUT"
        rm -f "$HC_OUT"
        exit 1
    fi
    rm -f "$HC_OUT"
fi

# Healthcheck passed; create the session.
"$PYTHON_BIN" "$RECORD" start

SID="$("$PYTHON_BIN" - <<PY
import json, os
p = os.path.join(os.environ.get("HOMEBASE_ROOT", "$HOMEBASE_ROOT"), "agents", ".rec-session.json")
print(json.load(open(p))["session_id"] if os.path.exists(p) else "")
PY
)"

if [[ -z "$SID" ]]; then
    update_state "error" "" '{"error":"start_session: record_session.py did not write a marker"}'
    notify "Homebase" "Failed to start session"
    exit 1
fi
SESSION_DIR="$HOMEBASE_ROOT/recordings/$SID"

update_state "recording" "$SID" '{"message":"recording in progress","last_prd":null,"last_handoff":null}'

# Drive the configured recorder (screen-studio | file -- see providers/recorder/) and,
# if present, the configured dictation provider's optional start() control.
recorder_start "$SESSION_DIR"
dictation_start

# Spawn the during-record liveness monitor (the real guard). It self-exits at Stop when
# the session marker clears. Record its PID so Stop can also kill it explicitly.
if [[ "$DRY_RUN" != "1" ]]; then
    nohup "$PYTHON_BIN" "$LIVENESS" --session "$SID" \
        >"$HOMEBASE_ROOT/agents/session_liveness.log" 2>&1 &
    echo $! > "$SESSION_DIR/.liveness.pid"
fi

# Start the mic backup track via the launchd agent (com.homebase.audiobackup). It runs
# under launchd's OWN Microphone permission, NOT under SwiftBar -- SwiftBar has no mic
# access, so a stream it spawned itself would be digital silence. The agent reads the
# active session marker, RMS-probes the mic, refuses to record silence, and self-stops at
# Stop. A backup failure does NOT block the session (the agent writes .capture-alert ->
# menu dot red). See menubar/launchd/README.md for installing this service.
if [[ "$DRY_RUN" != "1" ]]; then
    if launchctl kickstart -k "gui/$(id -u)/com.homebase.audiobackup" 2>/dev/null; then
        echo "Backup audio agent started (launchd, permissioned context)."
    else
        notify "Homebase" "WARNING: backup audio agent not loaded. Your dictation provider is your ONLY narration path."
        echo "[warn] Backup audio agent failed to kickstart (is com.homebase.audiobackup loaded?)."
    fi
fi

notify "Homebase" "Recording: $SID"
echo "Started session $SID (liveness monitor armed)"
