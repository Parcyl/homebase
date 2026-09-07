#!/usr/bin/env bash
# Copy the latest prds/<session>/handoff-prompt.md to clipboard via pbcopy.
# Written by intelligence/app/io.py.

set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../lib/state.sh"

HANDOFF="$(latest_handoff || true)"
if [[ -z "$HANDOFF" || ! -f "$HANDOFF" ]]; then
    notify "Homebase" "No handoff prompt yet"
    echo "no handoff found"
    exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] would copy $HANDOFF"
    exit 0
fi

if ! command -v pbcopy >/dev/null 2>&1; then
    echo "pbcopy unavailable; handoff path: $HANDOFF"
    exit 1
fi

pbcopy < "$HANDOFF"
notify "Homebase" "Handoff prompt copied to clipboard"
echo "copied $HANDOFF"
