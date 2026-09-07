#!/usr/bin/env bash
# Open the most recent recordings/<session>/DIGEST.md in the editor.
# Written by pipeline/doc_generator.py, if you're running that watcher.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

DIGEST="$(latest_digest || true)"
if [[ -z "$DIGEST" || ! -f "$DIGEST" ]]; then
    notify "Homebase" "No digest yet -- record a session first"
    exit 0
fi

open_in_editor "$DIGEST"
echo "Opened $DIGEST"
