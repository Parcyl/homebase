#!/usr/bin/env bash
# Reveal HOMEBASE_ROOT/inbox/ in Finder. Written by pipeline/pipeline_watcher.py.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

INBOX="$HOMEBASE_ROOT/inbox"
mkdir -p "$INBOX"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would open $INBOX"
    exit 0
fi

open "$INBOX"
