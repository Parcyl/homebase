#!/usr/bin/env bash
# Open Terminal and tail the launchd service logs (see menubar/launchd/).

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

LOGS=(
    "$HOMEBASE_ROOT/agents/pipeline_watcher.stdout.log"
    "$HOMEBASE_ROOT/agents/docgen_watcher.stdout.log"
    "$HOMEBASE_ROOT/agents/intelligence.stdout.log"
    "$HOMEBASE_ROOT/agents/audiobackup.stdout.log"
)
touch "${LOGS[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would tail ${LOGS[*]}"
    exit 0
fi

CMD="tail -F \"${LOGS[0]}\" \"${LOGS[1]}\" \"${LOGS[2]}\" \"${LOGS[3]}\""
osascript -e "tell application \"Terminal\" to do script \"$CMD\""
