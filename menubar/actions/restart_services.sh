#!/usr/bin/env bash
# Restart the intelligence spine (via run.sh) and the watcher daemons (via launchctl).
# Best-effort -- a service that isn't installed is silently skipped.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

# Resolved relative to this script's own fixed location on disk, not $HOMEBASE_ROOT -- see
# start_session.sh for why.
INTELLIGENCE_DIR="$HERE/../../intelligence"
WATCHER_LABELS=("com.homebase.pipeline.watcher" "com.homebase.docgen.watcher")

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would restart intelligence at $INTELLIGENCE_DIR and: ${WATCHER_LABELS[*]}"
    update_state "idle" "" '{"message":"[dry-run] services restarted"}'
    exit 0
fi

# Kill any running server bound to the configured port (ignore failures)
PORT="${LANGGRAPH_PORT:-8080}"
INTELLIGENCE_PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)
if [[ -n "$INTELLIGENCE_PIDS" ]]; then
    echo "$INTELLIGENCE_PIDS" | xargs kill 2>/dev/null || true
    sleep 1
fi

# Start the intelligence spine detached so this script returns immediately
if [[ -x "$INTELLIGENCE_DIR/run.sh" ]]; then
    ( cd "$INTELLIGENCE_DIR" && nohup ./run.sh > "$HOMEBASE_ROOT/agents/intelligence.stdout.log" 2>&1 & ) || true
fi

# Restart each watcher via launchctl if it's loaded
for label in "${WATCHER_LABELS[@]}"; do
    if launchctl list 2>/dev/null | grep -q "$label"; then
        launchctl kickstart -k "gui/$(id -u)/$label" 2>/dev/null || \
            launchctl stop "$label" 2>/dev/null || true
    fi
done

update_state "idle" "" '{"message":"services restarted"}'
notify "Homebase" "Services restarted"
echo "restart attempted"
